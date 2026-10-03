"""Patient report schemas. Mirror in frontend/src/types/api.ts."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel

from app.db.models import IngestionStatus, ReportType
from app.schemas.common import UtcDateTime


class ReportOut(BaseModel):
    """Report metadata: visible to reception, admin and doctors (no contents)."""

    id: UUID
    patient_id: UUID
    consultation_id: UUID | None
    title: str
    report_type: ReportType
    report_date: date | None
    mime_type: str
    size_bytes: int
    page_count: int | None
    ingestion_status: IngestionStatus
    # Why indexing failed / why the report has no searchable text.
    ingestion_error: str | None
    # Lab PDFs: the clinic's generated report of an order, or the lab machine's own PDF.
    lab_order_id: UUID | None = None
    is_generated: bool = False
    created_at: UtcDateTime
    updated_at: UtcDateTime


class ReportUrlOut(BaseModel):
    """Short-lived signed URL for viewing the file (doctors only)."""

    url: str
    mime_type: str
    expires_in: int
