"""Uploaded patient reports: upload, list, signed URLs, retry.

Reception, admin and doctors may upload and see report metadata. Only doctors get signed URLs
(the file contents). Files go to Storage first; if saving the row fails, the file is removed.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from anyio import to_thread
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Consultation,
    IngestionStatus,
    LabOrder,
    PatientReport,
    RecordAccessAction,
    RecordSourceType,
    ReportType,
)
from app.services.booking.actor import StaffActor
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success
from app.services.ingestion.jobs import enqueue
from app.services.records.access import clinician_check, is_clinician, report_patient
from app.services.records.audit import log_access
from app.services.records.storage import ReportStorage, report_path

_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


def sniff_mime_type(data: bytes) -> str | None:
    """The file type from its leading bytes (the browser's Content-Type is not trusted)."""
    head = data[:1024]
    for signature, mime in _SIGNATURES:
        # Some PDF writers put a little junk before the header; allow it within the first 1 KB.
        if head.startswith(signature) or (mime == "application/pdf" and signature in head):
            return mime
    return None


@dataclass(frozen=True)
class NewReport:
    title: str
    report_type: ReportType
    report_date: date | None
    data: bytes
    consultation_id: UUID | None = None
    # The lab's own (machine) PDF for an order: uploaded by lab staff, stored with the order's
    # report and never embedded (the order's structured results are).
    lab_order_id: UUID | None = None


async def upload_report(
    session: AsyncSession,
    storage: ReportStorage,
    actor: StaffActor,
    patient_id: UUID,
    report: NewReport,
    *,
    max_bytes: int,
) -> BookingResult[PatientReport]:
    if report.lab_order_id is not None:
        allowed_order = await _lab_attachment_check(session, actor, patient_id, report.lab_order_id)
        if not allowed_order.ok:
            return failure(allowed_order.code or BookingErrorCode.FORBIDDEN, allowed_order.message)
    else:
        allowed = await report_patient(session, actor, patient_id)
        if not allowed.ok:
            return failure(allowed.code or BookingErrorCode.FORBIDDEN, allowed.message)
    title = " ".join(report.title.split())
    if not title or len(title) > 200:
        return failure(
            BookingErrorCode.VALIDATION, "Give the report a title (up to 200 characters)."
        )
    if not report.data:
        return failure(BookingErrorCode.VALIDATION, "The file is empty.")
    if len(report.data) > max_bytes:
        return failure(
            BookingErrorCode.FILE_TOO_LARGE,
            f"The file is larger than {max_bytes // (1024 * 1024)} MB.",
        )
    mime_type = sniff_mime_type(report.data)
    if mime_type is None:
        return failure(BookingErrorCode.UNSUPPORTED_FILE_TYPE, "Upload a PDF, JPEG or PNG file.")
    if report.consultation_id is not None:
        found = await session.scalar(
            select(Consultation.id).where(
                Consultation.id == report.consultation_id,
                Consultation.patient_id == patient_id,
                Consultation.clinic_id == actor.clinic_id,
            )
        )
        if found is None:
            return failure(BookingErrorCode.NOT_FOUND, "Visit not found.")

    report_id = uuid.uuid4()
    path = report_path(actor.clinic_id, patient_id, report_id, mime_type)
    await to_thread.run_sync(storage.upload, path, report.data, mime_type)
    try:
        row = PatientReport(
            id=report_id,
            clinic_id=actor.clinic_id,
            patient_id=patient_id,
            consultation_id=report.consultation_id,
            uploaded_by=actor.user_id,
            title=title,
            report_type=report.report_type,
            report_date=report.report_date,
            storage_path=path,
            mime_type=mime_type,
            size_bytes=len(report.data),
            lab_order_id=report.lab_order_id,
        )
        session.add(row)
        await session.flush()
        if report.lab_order_id is None:
            await enqueue(session, actor.clinic_id, patient_id, RecordSourceType.REPORT, report_id)
        else:
            # Searchable through the order's results; the lab_result job marks it indexed.
            await enqueue(
                session,
                actor.clinic_id,
                patient_id,
                RecordSourceType.LAB_RESULT,
                report.lab_order_id,
            )
        log_access(
            session, actor, patient_id, RecordAccessAction.REPORT_UPLOAD, report_id=report_id
        )
        await session.commit()
    except Exception:
        await session.rollback()
        await to_thread.run_sync(storage.remove, path)
        raise
    return success(row)


async def _lab_attachment_check(
    session: AsyncSession, actor: StaffActor, patient_id: UUID, order_id: UUID
) -> BookingResult[UUID]:
    if not actor.is_lab:
        return failure(BookingErrorCode.FORBIDDEN, "Only lab staff can attach lab PDFs.")
    found = await session.scalar(
        select(LabOrder.id).where(
            LabOrder.id == order_id,
            LabOrder.clinic_id == actor.clinic_id,
            LabOrder.patient_id == patient_id,
        )
    )
    if found is None:
        return failure(BookingErrorCode.NOT_FOUND, "Lab order not found.")
    return success(found)


async def list_reports(
    session: AsyncSession, actor: StaffActor, patient_id: UUID
) -> BookingResult[list[PatientReport]]:
    allowed = await report_patient(session, actor, patient_id)
    if not allowed.ok:
        return failure(allowed.code or BookingErrorCode.FORBIDDEN, allowed.message)
    rows = await session.scalars(
        select(PatientReport)
        .where(PatientReport.patient_id == patient_id, PatientReport.clinic_id == actor.clinic_id)
        .order_by(PatientReport.report_date.desc().nulls_last(), PatientReport.created_at.desc())
    )
    return success(list(rows))


async def get_report(
    session: AsyncSession, actor: StaffActor, report_id: UUID
) -> BookingResult[PatientReport]:
    """Report metadata (status polling); for anyone who may upload."""
    if not (actor.is_front_desk or is_clinician(actor)):
        return failure(BookingErrorCode.FORBIDDEN, "You do not have access to reports.")
    row = await session.scalar(
        select(PatientReport).where(
            PatientReport.id == report_id, PatientReport.clinic_id == actor.clinic_id
        )
    )
    if row is None:
        return failure(BookingErrorCode.NOT_FOUND, "Report not found.")
    return success(row)


async def report_signed_url(
    session: AsyncSession,
    storage: ReportStorage,
    actor: StaffActor,
    report_id: UUID,
    *,
    expires_in: int,
) -> BookingResult[tuple[PatientReport, str]]:
    """A short-lived URL to view the file. Doctors only; every view is logged."""
    check = clinician_check(actor)
    if not check.ok:
        return failure(check.code or BookingErrorCode.FORBIDDEN, check.message)
    found = await get_report(session, actor, report_id)
    if not found.ok:
        return failure(found.code or BookingErrorCode.NOT_FOUND, found.message)
    row = found.unwrap()
    url = await to_thread.run_sync(storage.signed_url, row.storage_path, expires_in)
    log_access(session, actor, row.patient_id, RecordAccessAction.REPORT_VIEW, report_id=row.id)
    await session.commit()
    return success((row, url))


async def retry_report(
    session: AsyncSession, actor: StaffActor, report_id: UUID
) -> BookingResult[PatientReport]:
    """Queue a failed report for indexing again."""
    found = await get_report(session, actor, report_id)
    if not found.ok:
        return failure(found.code or BookingErrorCode.NOT_FOUND, found.message)
    row = found.unwrap()
    if row.ingestion_status is not IngestionStatus.FAILED:
        return failure(BookingErrorCode.INVALID_TRANSITION, "Only failed reports can be retried.")
    row.ingestion_status = IngestionStatus.PENDING
    row.ingestion_error = None
    await session.flush()
    await enqueue(session, row.clinic_id, row.patient_id, RecordSourceType.REPORT, row.id)
    await session.commit()
    return success(row)
