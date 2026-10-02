from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.db.models import AppointmentStatus, InboundChannel, InboundStatus
from app.schemas.common import Name, ShortText, UtcDateTime
from app.schemas.doctors import SlotOut


class InboundEnvelope(BaseModel):
    """The minimum needed to store and de-duplicate a request."""

    model_config = ConfigDict(extra="ignore")

    channel: InboundChannel
    external_ref: str = Field(min_length=1, max_length=200, pattern=r"\S")


class InboundBookingIn(InboundEnvelope):
    """A booking request from a WhatsApp or voice bot.

    `external_ref` is the bot's unique id for this request (e.g. the WhatsApp message id);
    resending the same one never books twice. Without `doctor_id` and `requested_time` the
    request is kept for the front desk to handle.
    """

    caller_phone: str = Field(min_length=5, max_length=20)
    patient_name: Name
    doctor_id: UUID | None = None
    requested_time: AwareDatetime | None = None
    reason: ShortText = None


class InboundAppointmentOut(BaseModel):
    id: UUID
    token_number: int
    status: AppointmentStatus
    starts_at: UtcDateTime
    doctor_id: UUID
    doctor_name: str


class InboundBookingOut(BaseModel):
    request_id: UUID
    status: InboundStatus
    # True when this external_ref was already received; nothing new was booked.
    duplicate: bool
    appointment: InboundAppointmentOut | None
    error_code: str | None
    message: str
    # When the requested time could not be booked: free slots the bot can offer instead.
    suggested_slots: list[SlotOut]


class InboundRequestOut(BaseModel):
    """A bot request as the front desk sees it."""

    id: UUID
    channel: InboundChannel
    external_ref: str | None
    caller_phone: str | None
    parsed_patient_name: str | None
    requested_doctor_id: UUID | None
    requested_doctor_name: str | None
    requested_time: UtcDateTime | None
    status: InboundStatus
    error: str | None
    appointment_id: UUID | None
    created_at: UtcDateTime
