from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.db.models import AppointmentSource, AppointmentStatus, Gender
from app.schemas.common import Name, NoteText, ShortText, UtcDateTime


class PatientOut(BaseModel):
    id: UUID
    full_name: str
    phone: str
    alternate_phone: str | None
    gender: Gender | None
    date_of_birth: date | None
    age_years: int | None
    # date_of_birth when known, else the recorded age_years.
    age: int | None
    address: str | None
    notes: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class _PatientFields(BaseModel):
    alternate_phone: ShortText = None
    gender: Gender | None = None
    date_of_birth: date | None = None
    age_years: int | None = Field(default=None, ge=0, le=130)
    address: ShortText = None
    notes: NoteText = None

    @model_validator(mode="after")
    def _dob_not_in_future(self) -> Self:
        if self.date_of_birth is not None and self.date_of_birth > date.today():
            raise ValueError("Date of birth cannot be in the future.")
        return self


class PatientCreate(_PatientFields):
    full_name: Name
    phone: str = Field(min_length=5, max_length=20)


class PatientUpdate(_PatientFields):
    """Only fields present in the request are changed (explicit null clears a field)."""

    full_name: Name | None = None
    phone: str | None = Field(default=None, min_length=5, max_length=20)


class PatientVisitOut(BaseModel):
    id: UUID
    starts_at: UtcDateTime
    appointment_date: date
    token_number: int
    status: AppointmentStatus
    source: AppointmentSource
    doctor_name: str
    reason_for_visit: str | None


class PatientDetailOut(PatientOut):
    appointments: list[PatientVisitOut]


class DuplicateOut(BaseModel):
    patient: PatientOut
    reason: Literal["same_phone", "similar_name", "same_phone_similar_name"]
