"""Bot job queue (table `bot_jobs`), the same pattern as the ingestion queue.

Kinds:
- `inbound`: ref_id = channel_messages.id; run the conversation turn, then send the replies.
- `status`: payload = a WhatsApp delivery status; applied once the message it refers to exists.
- `outbox`: ref_id = message_outbox.id; (re)send one queued message.

Jobs are enqueued in the transaction that stores what they refer to. The worker claims them
with FOR UPDATE SKIP LOCKED in arrival order.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import bindparam

JobKind = Literal["inbound", "status", "outbox"]

STALE_PROCESSING = timedelta(minutes=10)
BASE_BACKOFF_SECONDS = 5

_ENQUEUE = text(
    """
    insert into public.bot_jobs (clinic_id, kind, ref_id, payload)
    values (:clinic_id, :kind, :ref_id, :payload)
    on conflict (kind, ref_id) where status = 'pending' and ref_id is not null do nothing
    """
).bindparams(bindparam("payload", type_=JSONB))


async def enqueue(
    session: AsyncSession,
    clinic_id: UUID,
    kind: JobKind,
    *,
    ref_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Queue a job. Does not commit."""
    await session.execute(
        _ENQUEUE,
        {"clinic_id": clinic_id, "kind": kind, "ref_id": ref_id, "payload": payload or {}},
    )


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    clinic_id: UUID
    kind: JobKind
    ref_id: UUID | None
    payload: dict[str, Any]
    attempts: int


_CLAIM = """
    update public.bot_jobs j
    set status = 'processing', attempts = j.attempts + 1, updated_at = now()
    where j.id = (
      select q.id from public.bot_jobs q
      where ((q.status = 'pending' and q.run_after <= now())
         or (q.status = 'processing' and q.updated_at < now() - cast(:stale as interval)))
        and {scope}
      order by q.run_after, q.created_at
      for update skip locked
      limit 1
    )
    returning j.id, j.clinic_id, j.kind, j.ref_id, j.payload, j.attempts
"""
_ONE_CLINIC = text(_CLAIM.format(scope="q.clinic_id = :clinic_id"))
# Like the ingestion worker, the background worker leaves pytest's throwaway clinics alone.
_ALL_CLINICS = text(
    _CLAIM.format(
        scope="not exists (select 1 from public.clinics c "
        "where c.id = q.clinic_id and c.name like 'pytest-clinic-%')"
    )
)


async def claim_next(session: AsyncSession, *, clinic_id: UUID | None = None) -> ClaimedJob | None:
    """Claim one due job (commits the claim so other workers skip it)."""
    stmt = _ONE_CLINIC if clinic_id is not None else _ALL_CLINICS
    params: dict[str, object] = {"stale": STALE_PROCESSING}
    if clinic_id is not None:
        params["clinic_id"] = clinic_id
    row = (await session.execute(stmt, params)).first()
    await session.commit()
    if row is None:
        return None
    return ClaimedJob(
        id=row[0],
        clinic_id=row[1],
        kind=row[2],
        ref_id=row[3],
        payload=dict(row[4] or {}),
        attempts=row[5],
    )


async def mark_done(session: AsyncSession, job_id: UUID, note: str | None = None) -> None:
    await session.execute(
        text("update public.bot_jobs set status = 'done', last_error = :note where id = :id"),
        {"id": job_id, "note": note},
    )
    await session.commit()


async def mark_failed(
    session: AsyncSession, job: ClaimedJob, error: str, max_attempts: int
) -> bool:
    """Retry later with exponential backoff, or give up. Returns True if it gave up."""
    give_up = job.attempts >= max_attempts
    delay = BASE_BACKOFF_SECONDS * 2 ** (job.attempts - 1)
    await session.execute(
        text(
            """
            update public.bot_jobs
            set status = cast(:status as public.job_status), last_error = :error,
                run_after = now() + cast(:delay as interval)
            where id = :id
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
