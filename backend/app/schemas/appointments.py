from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel

from app.db.models import (
    ActorType,
    AppointmentSource,
    AppointmentStatus,
    Gender,
)
from app.schemas.common import NoteText, ShortText, UtcDateTime


class PatientBrief(BaseModel):
    id: UUID
    full_name: str
    # Null for doctors: they do not need patients' contact details.
    phone: str | None
    gender: Gender | None
    age: int | None


class DoctorBrief(BaseModel):
    id: UUID
    full_name: str
    specialization: str


class AppointmentOut(BaseModel):
    id: UUID
    token_number: int
    status: AppointmentStatus
    source: AppointmentSource
    starts_at: UtcDateTime
    ends_at: UtcDateTime
    appointment_date: date
    reason_for_visit: str | None
    notes: str | None
    external_ref: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime
    patient: PatientBrief
    doctor: DoctorBrief


class AppointmentEventOut(BaseModel):
    id: int
    from_status: AppointmentStatus | None
    to_status: AppointmentStatus
    actor_type: ActorType
    channel: str
    changed_by_name: str | None
    note: str | None
    created_at: UtcDateTime


class AppointmentDetailOut(AppointmentOut):
    events: list[AppointmentEventOut]


class AppointmentSummaryOut(BaseModel):
    date: date
    total: int
    by_status: dict[AppointmentStatus, int]
    by_source: dict[AppointmentSource, int]


class AppointmentCreate(BaseModel):
    patient_id: UUID
    doctor_id: UUID
    starts_at: AwareDatetime
    source: Literal[AppointmentSource.WALK_IN, AppointmentSource.PHONE, AppointmentSource.MANUAL]
    reason_for_visit: ShortText = None
    notes: NoteText = None
    squeeze_in: bool = False


class StatusUpdate(BaseModel):
    status: AppointmentStatus
    note: ShortText = None


class RescheduleIn(BaseModel):
    starts_at: AwareDatetime
    squeeze_in: bool = False


class RejectIn(BaseModel):
    reason: ShortText = None


class BotNotificationOut(BaseModel):
    """What happened to the patient's WhatsApp / voice message about a decision."""

    # queued | window_closed | opted_out | no_consent | limit | not_configured | no_conversation
    status: str
    channel: str
    phone: str


class DecisionOut(AppointmentOut):
    notification: BotNotificationOut | None = None
