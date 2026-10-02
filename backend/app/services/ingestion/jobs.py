"""Ingestion job queue (table `ingestion_jobs`).

Jobs are enqueued inside the transaction that changes a record, so a committed change always
has a job. Repeated triggers for the same source collapse into one pending job (partial unique
index). The worker claims jobs with FOR UPDATE SKIP LOCKED.
"""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RecordSourceType

# A job left in `processing` this long (crashed worker) is claimed again.
STALE_PROCESSING = timedelta(minutes=10)
BASE_BACKOFF_SECONDS = 10

_ENQUEUE = text(
    """
    insert into public.ingestion_jobs (clinic_id, patient_id, source_type, source_id)
    values (:clinic_id, :patient_id, cast(:source_type as public.record_source_type), :source_id)
    on conflict (source_type, source_id) where status = 'pending' do nothing
    """
)


async def enqueue(
    session: AsyncSession,
    clinic_id: UUID,
    patient_id: UUID,
    source_type: RecordSourceType,
    source_id: UUID,
) -> None:
    """Queue (re)indexing of one source. Does not commit."""
    await session.execute(
        _ENQUEUE,
        {
            "clinic_id": clinic_id,
            "patient_id": patient_id,
            "source_type": source_type.value,
            "source_id": source_id,
        },
    )


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    clinic_id: UUID
    patient_id: UUID
    source_type: RecordSourceType
    source_id: UUID
    attempts: int


_CLAIM = """
    update public.ingestion_jobs j
    set status = 'processing', attempts = j.attempts + 1, updated_at = now()
    where j.id = (
      select q.id from public.ingestion_jobs q
      where ((q.status = 'pending' and q.run_after <= now())
         or (q.status = 'processing' and q.updated_at < now() - cast(:stale as interval)))
        and {scope}
      order by q.run_after
      for update skip locked
      limit 1
    )
    returning j.id, j.clinic_id, j.patient_id, j.source_type::text, j.source_id, j.attempts
"""
_ONE_CLINIC = text(_CLAIM.format(scope="q.clinic_id = :clinic_id"))
# The background worker leaves pytest's throwaway clinics alone: tests share the dev database
# and process their own jobs (see tests/conftest.py, clinic names "pytest-clinic-...").
_ALL_CLINICS = text(
    _CLAIM.format(
        scope="not exists (select 1 from public.clinics c "
        "where c.id = q.clinic_id and c.name like 'pytest-clinic-%')"
    )
)


async def claim_next(session: AsyncSession, *, clinic_id: UUID | None = None) -> ClaimedJob | None:
    """Claim one due job (commits the claim so other workers skip it)."""
    stale = STALE_PROCESSING
    stmt = _ONE_CLINIC if clinic_id is not None else _ALL_CLINICS
    params: dict[str, object] = {"stale": stale}
    if clinic_id is not None:
        params["clinic_id"] = clinic_id
    row = (await session.execute(stmt, params)).first()
    await session.commit()
    if row is None:
        return None
    return ClaimedJob(
        id=row[0],
        clinic_id=row[1],
        patient_id=row[2],
        source_type=RecordSourceType(row[3]),
        source_id=row[4],
        attempts=row[5],
    )


async def mark_done(session: AsyncSession, job_id: UUID) -> None:
    await session.execute(
        text("update public.ingestion_jobs set status = 'done', last_error = null where id = :id"),
        {"id": job_id},
    )
    await session.commit()


async def mark_failed(
    session: AsyncSession, job: ClaimedJob, error: str, max_attempts: int
) -> bool:
    """Retry later with exponential backoff, or give up. Returns True if it gave up.

    If a newer pending job for the same source exists, that one supersedes this retry.
    """
    give_up = job.attempts >= max_attempts
    delay = BASE_BACKOFF_SECONDS * 2 ** (job.attempts - 1)
    await session.execute(
        text(
            """
            update public.ingestion_jobs j
            set status = case
                  when :status = 'pending' and exists (
                    select 1 from public.ingestion_jobs p
                    where p.source_type = j.source_type and p.source_id = j.source_id
                      and p.status = 'pending' and p.id <> j.id
                  ) then 'done'::public.job_status
                  else cast(:status as public.job_status)
                end,
                last_error = :error,
                run_after = now() + cast(:delay as interval)
            where j.id = :id
            """
        ),
        {
            "id": job.id,
            "status": "failed" if give_up else "pending",
            "error": error[:2000],
            "delay": timedelta(seconds=delay),
        },
    )
    await session.commit()
    return give_up
