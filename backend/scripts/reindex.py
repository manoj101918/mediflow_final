"""Rebuild the chatbot's index (patient_record_chunks) for one patient or everyone.

    cd backend
    uv run python -m scripts.reindex --patient <patient-id>
    uv run python -m scripts.reindex --all

Queues every indexable source (medical profile, finalized visits, reports) and processes the
queue inline with the configured providers (RAG_FAKE_LLM=true uses fake embeddings). Unchanged
sources are skipped without re-embedding, so re-running is cheap. Run it after changing
EMBEDDING_MODEL, since chunks are stored per embedding model.
"""

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import text

from app.db.models import RecordSourceType
from app.db.session import dispose_engine, get_sessionmaker
from app.services.ingestion.jobs import enqueue
from app.services.ingestion.worker import default_deps, run_pending

_SOURCES = text(
    """
    select * from (
      select clinic_id, id as patient_id, 'profile' as kind, id as source_id
        from public.patients p
        where exists (select 1 from public.patient_medical_profiles m where m.patient_id = p.id)
      union all
      select clinic_id, patient_id, 'consultation', id from public.consultations
        where status = 'finalized'
      union all
      -- Lab PDFs are searchable through their order's structured results.
      select clinic_id, patient_id, 'report', id from public.patient_reports
        where lab_order_id is null
      union all
      select o.clinic_id, o.patient_id, 'lab_result', o.id from public.lab_orders o
        where exists (
          select 1 from public.lab_order_items i where i.order_id = o.id and i.status = 'released'
        )
    ) s
    where cast(:patient as uuid) is null or s.patient_id = cast(:patient as uuid)
    """
)


async def main(patient: UUID | None) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        rows = [
            (UUID(str(r[0])), UUID(str(r[1])), RecordSourceType(str(r[2])), UUID(str(r[3])))
            for r in await session.execute(_SOURCES, {"patient": patient})
        ]
        clinics = {clinic_id for clinic_id, *_ in rows}
        # Jobs already waiting (backing off after errors, or given up) run now with fresh
        # attempts, instead of a second job being queued behind them.
        await session.execute(
            text(
                "update public.ingestion_jobs set status = 'pending', attempts = 0, "
                "run_after = now(), last_error = null where status in ('pending', 'failed') "
                "and (cast(:patient as uuid) is null or patient_id = cast(:patient as uuid)) "
                "and not exists (select 1 from public.ingestion_jobs p where p.status = 'pending' "
                "and p.source_type = ingestion_jobs.source_type "
                "and p.source_id = ingestion_jobs.source_id and p.id <> ingestion_jobs.id)"
            ),
            {"patient": patient},
        )
        for clinic_id, patient_id, kind, source_id in rows:
            await enqueue(session, clinic_id, patient_id, kind, source_id)
        # Reports go back to "pending" so the chart shows them being re-indexed.
        await session.execute(
            text(
                "update public.patient_reports set ingestion_status = 'pending', "
                "ingestion_error = null where (cast(:patient as uuid) is null "
                "or patient_id = cast(:patient as uuid)) and ingestion_status <> 'processing'"
            ),
            {"patient": patient},
        )
        await session.commit()
    print(f"queued {len(rows)} sources")

    deps = default_deps()
    total = 0
    for clinic_id in clinics:
        total += await run_pending(sessionmaker, deps, clinic_id=clinic_id)
    print(f"processed {total} jobs with embedding model {deps.model}")
    await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--patient", type=UUID, help="patient id")
    target.add_argument("--all", action="store_true", help="every patient in every clinic")
    args = parser.parse_args()
    asyncio.run(main(args.patient))
