"""Patient reports: upload (multipart), list, status, signed URL, retry."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.results import HTTP_STATUS, unwrap
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import PatientReport, ReportType
from app.deps import AuthUser, DbSession, staff_actor
from app.schemas.reports import ReportOut, ReportUrlOut
from app.services.booking.results import BookingErrorCode
from app.services.records.reports import (
    NewReport,
    get_report,
    list_reports,
    report_signed_url,
    retry_report,
    upload_report,
)
from app.services.records.storage import ReportStorage, get_report_storage

router = APIRouter(tags=["reports"])

Storage = Annotated[ReportStorage, Depends(get_report_storage)]

_READ_CHUNK = 1024 * 1024


def report_out(report: PatientReport) -> ReportOut:
    return ReportOut(
        id=report.id,
        patient_id=report.patient_id,
        consultation_id=report.consultation_id,
        title=report.title,
        report_type=report.report_type,
        report_date=report.report_date,
        mime_type=report.mime_type,
        size_bytes=report.size_bytes,
        page_count=report.page_count,
        ingestion_status=report.ingestion_status,
        ingestion_error=report.ingestion_error,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


async def read_limited(file: UploadFile, max_bytes: int) -> bytes | None:
    """The file's bytes, or None as soon as it exceeds max_bytes (never buffers more)."""
    data = bytearray()
    while chunk := await file.read(_READ_CHUNK):
        data.extend(chunk)
        if len(data) > max_bytes:
            return None
    return bytes(data)


@router.post("/patients/{patient_id}/reports", status_code=status.HTTP_201_CREATED)
async def upload(
    patient_id: UUID,
    session: DbSession,
    user: AuthUser,
    storage: Storage,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(max_length=200)],
    report_type: Annotated[ReportType, Form()],
    report_date: Annotated[date | None, Form()] = None,
    consultation_id: Annotated[UUID | None, Form()] = None,
) -> ReportOut:
    """Upload a PDF/JPEG/PNG (type checked from its bytes). Indexing runs in the background."""
    max_bytes = get_settings().report_max_mb * 1024 * 1024
    data = await read_limited(file, max_bytes)
    if data is None:
        raise AppError(
            HTTP_STATUS[BookingErrorCode.FILE_TOO_LARGE],
            BookingErrorCode.FILE_TOO_LARGE.value,
            f"The file is larger than {get_settings().report_max_mb} MB.",
        )
    report = unwrap(
        await upload_report(
            session,
            storage,
            staff_actor(user),
            patient_id,
            NewReport(
                title=title,
                report_type=report_type,
                report_date=report_date,
                data=data,
                consultation_id=consultation_id,
            ),
            max_bytes=max_bytes,
        )
    )
    return report_out(report)


@router.get("/patients/{patient_id}/reports")
async def list_patient_reports(
    patient_id: UUID, session: DbSession, user: AuthUser
) -> list[ReportOut]:
    return [
        report_out(r) for r in unwrap(await list_reports(session, staff_actor(user), patient_id))
    ]


@router.get("/reports/{report_id}")
async def get_patient_report(report_id: UUID, session: DbSession, user: AuthUser) -> ReportOut:
    """Metadata only (poll while pending/processing)."""
    return report_out(unwrap(await get_report(session, staff_actor(user), report_id)))


@router.get("/reports/{report_id}/url")
async def get_report_url(
    report_id: UUID, session: DbSession, user: AuthUser, storage: Storage
) -> ReportUrlOut:
    ttl = get_settings().signed_url_ttl_seconds
    report, url = unwrap(
        await report_signed_url(session, storage, staff_actor(user), report_id, expires_in=ttl)
    )
    return ReportUrlOut(url=url, mime_type=report.mime_type, expires_in=ttl)


@router.post("/reports/{report_id}/retry")
async def retry(report_id: UUID, session: DbSession, user: AuthUser) -> ReportOut:
    return report_out(unwrap(await retry_report(session, staff_actor(user), report_id)))
