"""Ingestion worker: claims jobs from `ingestion_jobs` and (re)indexes their sources.

One asyncio task per API process, started in the FastAPI lifespan (we run uvicorn without
--reload, so the process starts it once) and cancelled on shutdown. Tests and scripts call
`run_pending()` directly instead.

Failures:
- ExtractionError (damaged / password-protected PDF) is permanent: the report is marked
  `failed` with a readable message and waits for a manual Retry.
- Anything else (Storage, embedding provider, database) is retried with backoff up to
  INGESTION_MAX_ATTEMPTS; the report shows `failed` once retries are exhausted.
Only job ids and error types are logged, never record text.
"""

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import structlog
from anyio import to_thread
from langchain_core.embeddings import Embeddings
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.models import (
    ExtractionMethod,
    IngestionStatus,
    PatientReport,
    RecordSourceType,
)
from app.services.booking.timeutil import clinic_tz, local_date
from app.services.ingestion import jobs
from app.services.ingestion.chunking import chunk_report_pages, chunk_source
from app.services.ingestion.extract import ExtractionError, extract_pdf, looks_scanned
from app.services.ingestion.indexer import IndexResult, index_source, remove_source
from app.services.ingestion.render import render_consultation, render_profile
from app.services.labs.pdf import build_report_data, render_report
from app.services.labs.render import render_lab_order
from app.services.rag.providers import (
    ProviderNotConfiguredError,
    embedding_model_name,
    get_embeddings,
)
from app.services.records.storage import ReportStorage, get_report_storage

logger = structlog.get_logger(__name__)

# How often a paused worker (provider key missing) checks the configuration again.
PROVIDER_RETRY_SECONDS = 60

NO_TEXT_IMAGE = "Images are stored and viewable, but their text can't be searched."
NO_TEXT_SCAN = (
    "This PDF has no text layer (it looks scanned). It is stored and viewable, "
    "but its contents can't be searched."
)


@dataclass(frozen=True)
class IngestionDeps:
    embeddings: Embeddings
    model: str
    storage: ReportStorage
    settings: Settings


def default_deps() -> IngestionDeps:
    settings = get_settings()
    return IngestionDeps(
        embeddings=get_embeddings(),
        model=embedding_model_name(settings),
        storage=get_report_storage(),
        settings=settings,
    )


async def _index_consultation(
    session: AsyncSession, deps: IngestionDeps, job: jobs.ClaimedJob
) -> IndexResult | None:
    source = await render_consultation(session, job.source_id)
    if source is None:
        await remove_source(session, RecordSourceType.CONSULTATION, job.source_id)
        return None
    s = deps.settings
    return await index_source(
        session,
        deps.embeddings,
        deps.model,
        clinic_id=source.clinic_id,
        patient_id=source.patient_id,
        source_type=RecordSourceType.CONSULTATION,
        source_id=job.source_id,
        source_date=source.source_date,
        chunks=chunk_source(source, s.rag_chunk_size, s.rag_chunk_overlap),
    )


async def _index_profile(
    session: AsyncSession, deps: IngestionDeps, job: jobs.ClaimedJob
) -> IndexResult | None:
    source = await render_profile(session, job.source_id)
    if source is None:
        await remove_source(session, RecordSourceType.PROFILE, job.source_id)
        return None
    s = deps.settings
    return await index_source(
        session,
        deps.embeddings,
        deps.model,
        clinic_id=source.clinic_id,
        patient_id=source.patient_id,
        source_type=RecordSourceType.PROFILE,
        source_id=job.source_id,
        source_date=source.source_date,
        chunks=chunk_source(source, s.rag_chunk_size, s.rag_chunk_overlap),
    )


async def _set_report(session: AsyncSession, report_id: UUID, **values: object) -> None:
    report = await session.get(PatientReport, report_id)
    if report is not None:
        for name, value in values.items():
            setattr(report, name, value)
        await session.commit()


async def _index_report(
    session: AsyncSession, deps: IngestionDeps, job: jobs.ClaimedJob
) -> IndexResult | None:
    report = await session.get(PatientReport, job.source_id)
    if report is None:
        await remove_source(session, RecordSourceType.REPORT, job.source_id)
        return None
    # Plain values: the session is committed/rolled back below.
    path, mime = report.storage_path, report.mime_type
    title, kind, report_date = report.title, report.report_type, report.report_date
    report.ingestion_status = IngestionStatus.PROCESSING
    report.ingestion_error = None
    await session.commit()

    if mime != "application/pdf":
        await remove_source(session, RecordSourceType.REPORT, job.source_id)
        await _set_report(
            session,
            job.source_id,
            ingestion_status=IngestionStatus.NO_TEXT,
            ingestion_error=NO_TEXT_IMAGE,
        )
        return None

    data = await to_thread.run_sync(deps.storage.download, path)
    pdf = await to_thread.run_sync(extract_pdf, data)
    s = deps.settings
    if looks_scanned(pdf, s.min_text_chars_per_page):
        await remove_source(session, RecordSourceType.REPORT, job.source_id)
        await _set_report(
            session,
            job.source_id,
            page_count=pdf.page_count,
            extracted_text=None,
            ingestion_status=IngestionStatus.NO_TEXT,
            ingestion_error=NO_TEXT_SCAN,
        )
        return None

    result = await index_source(
        session,
        deps.embeddings,
        deps.model,
        clinic_id=job.clinic_id,
        patient_id=job.patient_id,
        source_type=RecordSourceType.REPORT,
        source_id=job.source_id,
        # Undated reports sort as of their indexing day.
        source_date=report_date or local_date(datetime.now(UTC), clinic_tz()),
        chunks=chunk_report_pages(
            pdf.pages,
            title=title,
            report_type=kind,
            report_date=report_date,
            chunk_size=s.rag_chunk_size,
            overlap=s.rag_chunk_overlap,
        ),
    )
    await _set_report(
        session,
        job.source_id,
        page_count=pdf.page_count,
        extracted_text="\n\n".join(
            f"[Page {n}]\n{text}" for n, text in enumerate(pdf.pages, start=1)
        ),
        extraction_method=ExtractionMethod.TEXT,
        ingestion_status=IngestionStatus.INDEXED,
        ingestion_error=None,
    )
    return result


async def _index_lab_result(
    session: AsyncSession, deps: IngestionDeps, job: jobs.ClaimedJob
) -> IndexResult | None:
    """A lab order's released results (source_id = lab_orders.id).

    Indexes one chunk per released test, then renders the clinic's PDF report, uploads it
    (replacing an earlier version) and marks the order's reports as indexed. The PDF's text is
    never embedded: the structured results already are.
    """
    source = await render_lab_order(session, job.source_id)
    if source is None:
        await remove_source(session, RecordSourceType.LAB_RESULT, job.source_id)
        await session.commit()
        return None
    s = deps.settings
    result = await index_source(
        session,
        deps.embeddings,
        deps.model,
        clinic_id=source.clinic_id,
        patient_id=source.patient_id,
        source_type=RecordSourceType.LAB_RESULT,
        source_id=job.source_id,
        source_date=source.source_date,
        chunks=chunk_source(source, s.rag_chunk_size, s.rag_chunk_overlap),
    )
    data = await build_report_data(session, job.source_id)
    report = await session.scalar(
        select(PatientReport).where(
            PatientReport.lab_order_id == job.source_id, PatientReport.is_generated
        )
    )
    if data is not None and report is not None:
        rendered = render_report(data)
        await to_thread.run_sync(
            lambda: deps.storage.upload(
                report.storage_path, rendered.data, "application/pdf", upsert=True
            )
        )
        report.size_bytes = len(rendered.data)
        report.page_count = rendered.pages
        if data.amended and not report.title.endswith("(amended)"):
            report.title = f"{report.title} (amended)"
    await session.execute(
        update(PatientReport)
        .where(PatientReport.lab_order_id == job.source_id)
        .values(ingestion_status=IngestionStatus.INDEXED, ingestion_error=None)
    )
    await session.commit()
    return result


_HANDLERS = {
    RecordSourceType.CONSULTATION: _index_consultation,
    RecordSourceType.PROFILE: _index_profile,
    RecordSourceType.REPORT: _index_report,
    RecordSourceType.LAB_RESULT: _index_lab_result,
}


async def process_job(
    sessionmaker: async_sessionmaker[AsyncSession], deps: IngestionDeps, job: jobs.ClaimedJob
) -> None:
    """Index one claimed job and record the outcome on the job (and report)."""
    async with sessionmaker() as session:
        try:
            result = await _HANDLERS[job.source_type](session, deps, job)
        except ExtractionError as exc:
            await session.rollback()
            await _set_report(
                session,
                job.source_id,
                ingestion_status=IngestionStatus.FAILED,
                ingestion_error=str(exc),
            )
            await jobs.mark_done(session, job.id)
            logger.info("ingestion_unreadable", job_id=str(job.id))
            return
        except Exception as exc:
            await session.rollback()
            gave_up = await jobs.mark_failed(
                session,
                job,
                type(exc).__name__,
                deps.settings.ingestion_max_attempts,
            )
            if job.source_type is RecordSourceType.REPORT:
                await _set_report(
                    session,
                    job.source_id,
                    ingestion_status=IngestionStatus.FAILED if gave_up else IngestionStatus.PENDING,
                    ingestion_error="Indexing failed. Use Retry to try again."
                    if gave_up
                    else "Indexing hit a temporary problem; retrying automatically.",
                )
            logger.warning(
                "ingestion_failed",
                job_id=str(job.id),
                source_type=job.source_type.value,
                attempts=job.attempts,
                gave_up=gave_up,
                error_type=type(exc).__name__,
            )
            return
        await jobs.mark_done(session, job.id)
        logger.info(
            "ingestion_done",
            job_id=str(job.id),
            source_type=job.source_type.value,
            chunks=result.chunks if result else 0,
            embedded=result.embedded if result else 0,
            unchanged=bool(result and result.unchanged),
        )


async def run_pending(
    sessionmaker: async_sessionmaker[AsyncSession],
    deps: IngestionDeps,
    *,
    clinic_id: UUID | None = None,
    max_jobs: int = 10_000,
) -> int:
    """Process due jobs until none are left. Returns how many ran.

    With `clinic_id`, only that clinic's jobs (tests, reindex script); without it, every
    clinic except throwaway pytest clinics (the background worker).
    """
    done = 0
    while done < max_jobs:
        async with sessionmaker() as session:
            job = await jobs.claim_next(session, clinic_id=clinic_id)
        if job is None:
            return done
        await process_job(sessionmaker, deps, job)
        done += 1
    return done


class IngestionWorker:
    """The background loop. start() is idempotent; stop() cancels and waits."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        poll_seconds: float,
        *,
        deps_factory: Callable[[], IngestionDeps] = default_deps,
        clinic_id: UUID | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._poll = poll_seconds
        self._deps_factory = deps_factory
        # Tests scope a worker to their own clinic; the app's worker serves every clinic.
        self._clinic_id = clinic_id
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if not self.running:
            self._task = asyncio.create_task(self._loop(), name="ingestion-worker")
            logger.info("ingestion_worker_started")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("ingestion_worker_stopped")

    async def _loop(self) -> None:
        deps: IngestionDeps | None = None
        paused = False
        while True:
            if deps is None:
                try:
                    deps = self._deps_factory()
                except ProviderNotConfiguredError as exc:
                    # Leave jobs queued (nothing is marked failed) until the key is configured.
                    if not paused:
                        logger.warning("ingestion_paused", reason=str(exc))
                        paused = True
                    await asyncio.sleep(PROVIDER_RETRY_SECONDS)
                    continue
            try:
                ran = await run_pending(
                    self._sessionmaker, deps, clinic_id=self._clinic_id, max_jobs=20
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # keep the loop alive (e.g. database briefly unreachable)
                logger.warning("ingestion_loop_error", error_type=type(exc).__name__)
                ran = 0
            if ran == 0:
                await asyncio.sleep(self._poll)
