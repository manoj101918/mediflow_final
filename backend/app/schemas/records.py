"""Clinical record schemas (doctor chart). Mirror in frontend/src/types/api.ts."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.db.models import AppointmentStatus, ConsultationStatus, Gender, IngestionStatus, ReportType
from app.schemas.common import ClinicalText, ItemText, NoteText, ShortClinicalText, UtcDateTime

Timing = Literal["before_food", "after_food", "with_food", "empty_stomach", "bedtime", "any"]
BloodGroup = Literal["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]


class Vitals(BaseModel):
    """All optional; only plausible ranges are accepted."""

    model_config = ConfigDict(extra="forbid")

    bp_systolic: int | None = Field(default=None, ge=40, le=300)
    bp_diastolic: int | None = Field(default=None, ge=20, le=200)
    pulse: int | None = Field(default=None, ge=20, le=250)
    temperature_c: float | None = Field(default=None, ge=30, le=45)
    weight_kg: float | None = Field(default=None, gt=0, le=400)
    height_cm: float | None = Field(default=None, gt=20, le=260)
    spo2: int | None = Field(default=None, ge=50, le=100)
    blood_sugar: float | None = Field(default=None, gt=0, le=1000)


class PrescriptionItemIn(BaseModel):
    medicine_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    strength: ItemText = None
    dosage_form: ItemText = None
    dose: ItemText = None
    route: ItemText = None
    frequency: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=30)] = None
    timing: Timing | None = None
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    instructions: NoteText = None


class PrescriptionItemOut(BaseModel):
    id: UUID
    medicine_name: str
    strength: str | None
    dosage_form: str | None
    dose: str | None
    route: str | None
    frequency: str | None
    timing: str | None
    duration_days: int | None
    instructions: str | None
    sort_order: int


class ConsultationIn(BaseModel):
    """Draft autosave. Only fields present are changed; `items` replaces the prescription."""

    chief_complaint: ShortClinicalText = None
    history: ClinicalText = None
    examination: ClinicalText = None
    diagnosis: ShortClinicalText = None
    advice: ClinicalText = None
    follow_up_date: date | None = None
    notes: ClinicalText = None
    vitals: Vitals | None = None
    items: list[PrescriptionItemIn] | None = Field(default=None, max_length=50)


class ConsultationOut(BaseModel):
    id: UUID
    appointment_id: UUID
    patient_id: UUID
    doctor_id: UUID
    chief_complaint: str | None
    history: str | None
    examination: str | None
    diagnosis: str | None
    advice: str | None
    follow_up_date: date | None
    notes: str | None
    vitals: Vitals
    status: ConsultationStatus
    finalized_at: UtcDateTime | None
    created_at: UtcDateTime
    updated_at: UtcDateTime
    items: list[PrescriptionItemOut]


class VisitOut(BaseModel):
    """The visit being written: its appointment and the consultation, if started."""

    appointment_id: UUID
    appointment_status: AppointmentStatus
    doctor_id: UUID
    # True when the signed-in doctor may edit it (own appointment, checked in / in consultation,
    # not finalized).
    editable: bool
    consultation: ConsultationOut | None


class CompleteOut(BaseModel):
    appointment_id: UUID
    appointment_status: AppointmentStatus
    consultation_id: UUID | None
    finalized: bool


class AddendumIn(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


class AddendumOut(BaseModel):
    id: UUID
    consultation_id: UUID
    author_name: str
    text: str
    created_at: UtcDateTime


class MedicalProfileIn(BaseModel):
    blood_group: BloodGroup | None = None
    allergies: list[Annotated[str, StringConstraints(max_length=100)]] = Field(
        default_factory=list, max_length=50
    )
    chronic_conditions: list[Annotated[str, StringConstraints(max_length=100)]] = Field(
        default_factory=list, max_length=50
    )


class MedicalProfileOut(BaseModel):
    blood_group: str | None
    allergies: list[str]
    chronic_conditions: list[str]
    updated_at: UtcDateTime | None


class ChartAppointmentOut(BaseModel):
    id: UUID
    token_number: int
    status: AppointmentStatus
    starts_at: UtcDateTime
    appointment_date: date
    reason_for_visit: str | None
    doctor_id: UUID
    doctor_name: str


class ChartOut(BaseModel):
    """Chart header. No phone numbers: doctors never see them."""

    patient_id: UUID
    full_name: str
    gender: Gender | None
    age: int | None
    date_of_birth: date | None
    profile: MedicalProfileOut
    visit_count: int
    last_visit: date | None
    appointment: ChartAppointmentOut | None


class ReportBriefOut(BaseModel):
    id: UUID
    title: str
    report_type: ReportType
    report_date: date | None
    mime_type: str
    ingestion_status: IngestionStatus


class HistoryVisitOut(BaseModel):
    consultation_id: UUID
    appointment_id: UUID
    visit_date: date
    token_number: int
    doctor_id: UUID
    doctor_name: str
    doctor_specialization: str
    chief_complaint: str | None
    history: str | None
    examination: str | None
    diagnosis: str | None
    advice: str | None
    follow_up_date: date | None
    notes: str | None
    vitals: Vitals
    finalized_at: UtcDateTime | None
    items: list[PrescriptionItemOut]
    addenda: list[AddendumOut]
    reports: list[ReportBriefOut]


class MedicationOut(BaseModel):
    item: PrescriptionItemOut
    consultation_id: UUID
    visit_date: date
    doctor_name: str
    end_date: date | None
    current: bool


class VitalsPointOut(BaseModel):
    consultation_id: UUID
    visit_date: date
    vitals: Vitals


class LatestPrescriptionOut(BaseModel):
    consultation_id: UUID
    visit_date: date
    doctor_name: str
    items: list[PrescriptionItemOut]
