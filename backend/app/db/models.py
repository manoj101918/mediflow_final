"""SQLAlchemy models mirroring supabase/migrations exactly.

The schema is owned by the SQL migrations (applied via Supabase MCP); these models never
create or alter tables. Constraints that matter to the service layer (e.g. the appointments
no-overlap exclusion constraint) are enforced by the database and surfaced as errors.
"""

import enum
from collections.abc import Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Enum,
    FetchedValue,
    ForeignKey,
    Identity,
    Numeric,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, deferred, mapped_column
from sqlalchemy.types import UserDefinedType

# Must match patient_record_chunks.embedding (vector(1024)) and settings.embedding_dim.
EMBEDDING_DIM = 1024


class UserRole(enum.StrEnum):
    ADMIN = "admin"
    RECEPTIONIST = "receptionist"
    DOCTOR = "doctor"
    LAB_TECHNICIAN = "lab_technician"
    LAB_SUPERVISOR = "lab_supervisor"


class AppointmentStatus(enum.StrEnum):
    PENDING_CONFIRMATION = "pending_confirmation"
    SCHEDULED = "scheduled"
    CHECKED_IN = "checked_in"
    IN_CONSULTATION = "in_consultation"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class AppointmentSource(enum.StrEnum):
    WALK_IN = "walk_in"
    PHONE = "phone"
    MANUAL = "manual"
    WHATSAPP = "whatsapp"
    VOICE = "voice"


class Gender(enum.StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class ActorType(enum.StrEnum):
    USER = "user"
    SYSTEM = "system"


class InboundChannel(enum.StrEnum):
    WHATSAPP = "whatsapp"
    VOICE = "voice"


class InboundStatus(enum.StrEnum):
    RECEIVED = "received"
    AUTO_BOOKED = "auto_booked"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class ConsultationStatus(enum.StrEnum):
    DRAFT = "draft"
    FINALIZED = "finalized"


class ReportType(enum.StrEnum):
    LAB = "lab"
    IMAGING = "imaging"
    DISCHARGE_SUMMARY = "discharge_summary"
    REFERRAL = "referral"
    OLD_PRESCRIPTION = "old_prescription"
    OTHER = "other"


class ExtractionMethod(enum.StrEnum):
    TEXT = "text"


class IngestionStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"
    # Stored and viewable, but no extractable text (images, scanned PDFs): not searchable.
    NO_TEXT = "no_text"


class RecordSourceType(enum.StrEnum):
    PROFILE = "profile"
    CONSULTATION = "consultation"
    REPORT = "report"
    # Released structured lab results of one order (source_id = lab_orders.id).
    LAB_RESULT = "lab_result"


class JobStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class ChatRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class LabCategory(enum.StrEnum):
    HAEMATOLOGY = "haematology"
    BIOCHEMISTRY = "biochemistry"
    HORMONES = "hormones"
    URINE = "urine"
    SEROLOGY = "serology"
    OTHER = "other"


class LabSampleType(enum.StrEnum):
    BLOOD = "blood"
    URINE = "urine"
    STOOL = "stool"
    SWAB = "swab"
    OTHER = "other"


class LabValueType(enum.StrEnum):
    NUMERIC = "numeric"
    TEXT = "text"
    CHOICE = "choice"


class LabRangeSex(enum.StrEnum):
    MALE = "male"
    FEMALE = "female"
    ANY = "any"


class LabPriority(enum.StrEnum):
    ROUTINE = "routine"
    URGENT = "urgent"
    STAT = "stat"


class LabOrderStatus(enum.StrEnum):
    ORDERED = "ordered"
    IN_PROGRESS = "in_progress"
    PARTIALLY_RELEASED = "partially_released"
    RELEASED = "released"
    CANCELLED = "cancelled"


class LabItemStatus(enum.StrEnum):
    ORDERED = "ordered"
    SAMPLE_COLLECTED = "sample_collected"
    SAMPLE_REJECTED = "sample_rejected"
    RESULT_ENTERED = "result_entered"
    VERIFIED = "verified"
    RELEASED = "released"
    CANCELLED = "cancelled"


class LabFlag(enum.StrEnum):
    NORMAL = "normal"
    LOW = "low"
    HIGH = "high"
    CRITICAL_LOW = "critical_low"
    CRITICAL_HIGH = "critical_high"
    ABNORMAL = "abnormal"


class RecordAccessAction(enum.StrEnum):
    CHART_OPEN = "chart_open"
    CHAT_QUESTION = "chat_question"
    REPORT_VIEW = "report_view"
    REPORT_UPLOAD = "report_upload"


def vector_literal(values: Sequence[float]) -> str:
    """pgvector's text form: '[0.1,0.2,...]'."""
    return "[" + ",".join(repr(float(x)) for x in values) + "]"


class Vector(UserDefinedType[str]):
    """pgvector `extensions.vector(dim)` (declarative only).

    Avoids a numpy/pgvector dependency. Vectors are written with explicit SQL,
    `cast(cast(:v as text) as extensions.vector)` with `vector_literal(...)`, compared inside
    Postgres, and never loaded into Python (keep the column deferred / out of selects).
    """

    cache_ok = True

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def get_col_spec(self, **_: Any) -> str:
        return f"extensions.vector({self.dim})"


def _pg_enum(enum_cls: type[enum.StrEnum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        schema="public",
        create_type=False,
        values_callable=lambda members: [m.value for m in members],
    )


def _uuid_pk() -> Mapped[UUID]:
    return mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))


class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True)}  # noqa: RUF012


class Clinic(Base):
    __tablename__ = "clinics"

    id: Mapped[UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, server_default=text("'Asia/Kolkata'"))
    lab_requires_verification: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Profile(Base):
    __tablename__ = "profiles"

    # References auth.users(id); auth users are created through the Supabase Admin API.
    id: Mapped[UUID] = mapped_column(primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    full_name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(_pg_enum(UserRole, "user_role"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), unique=True
    )
    full_name: Mapped[str] = mapped_column(Text)
    specialization: Mapped[str] = mapped_column(Text)
    consultation_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), server_default=text("0"))
    default_slot_minutes: Mapped[int] = mapped_column(server_default=text("15"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DoctorSchedule(Base):
    __tablename__ = "doctor_schedules"

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    doctor_id: Mapped[UUID] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"))
    # 0 = Monday ... 6 = Sunday (Python date.weekday()).
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time]
    end_time: Mapped[time]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class DoctorLeave(Base):
    __tablename__ = "doctor_leaves"

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    doctor_id: Mapped[UUID] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"))
    leave_date: Mapped[date]
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Patient(Base):
    __tablename__ = "patients"
    # Fetch trigger/server-maintained columns via RETURNING on UPDATE too (async-safe).
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    full_name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str] = mapped_column(Text)
    alternate_phone: Mapped[str | None] = mapped_column(Text)
    gender: Mapped[Gender | None] = mapped_column(_pg_enum(Gender, "gender"))
    date_of_birth: Mapped[date | None]
    age_years: Mapped[int | None] = mapped_column(SmallInteger)
    address: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), server_onupdate=FetchedValue()
    )


class Appointment(Base):
    __tablename__ = "appointments"
    # Fetch trigger/server-maintained columns via RETURNING on UPDATE too (async-safe).
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id"))
    doctor_id: Mapped[UUID] = mapped_column(ForeignKey("doctors.id"))
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    # Clinic-local date of starts_at, maintained by a BEFORE INSERT/UPDATE trigger.
    appointment_date: Mapped[date] = mapped_column(
        server_default=FetchedValue(), server_onupdate=FetchedValue()
    )
    status: Mapped[AppointmentStatus] = mapped_column(
        _pg_enum(AppointmentStatus, "appointment_status"), server_default=text("'scheduled'")
    )
    source: Mapped[AppointmentSource] = mapped_column(
        _pg_enum(AppointmentSource, "appointment_source")
    )
    token_number: Mapped[int]
    reason_for_visit: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    external_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), server_onupdate=FetchedValue()
    )


class AppointmentEvent(Base):
    __tablename__ = "appointment_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    appointment_id: Mapped[UUID] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"))
    from_status: Mapped[AppointmentStatus | None] = mapped_column(
        _pg_enum(AppointmentStatus, "appointment_status")
    )
    to_status: Mapped[AppointmentStatus] = mapped_column(
        _pg_enum(AppointmentStatus, "appointment_status")
    )
    changed_by: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    actor_type: Mapped[ActorType] = mapped_column(_pg_enum(ActorType, "actor_type"))
    # 'dashboard' | 'whatsapp' | 'voice'
    channel: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class InboundBookingRequest(Base):
    __tablename__ = "inbound_booking_requests"

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    channel: Mapped[InboundChannel] = mapped_column(_pg_enum(InboundChannel, "inbound_channel"))
    external_ref: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    caller_phone: Mapped[str | None] = mapped_column(Text)
    parsed_patient_name: Mapped[str | None] = mapped_column(Text)
    requested_doctor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("doctors.id", ondelete="SET NULL")
    )
    requested_time: Mapped[datetime | None]
    status: Mapped[InboundStatus] = mapped_column(
        _pg_enum(InboundStatus, "inbound_status"), server_default=text("'received'")
    )
    appointment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ---------------------------------------------------------------------------
# Phase 2: clinical records (backend-only tables; see *_phase2_rls_storage.sql)
# ---------------------------------------------------------------------------


class PatientMedicalProfile(Base):
    __tablename__ = "patient_medical_profiles"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    patient_id: Mapped[UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True
    )
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    blood_group: Mapped[str | None] = mapped_column(Text)
    allergies: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    chronic_conditions: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), server_onupdate=FetchedValue()
    )


class Consultation(Base):
    __tablename__ = "consultations"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    appointment_id: Mapped[UUID] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), unique=True
    )
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    doctor_id: Mapped[UUID] = mapped_column(ForeignKey("doctors.id"))
    chief_complaint: Mapped[str | None] = mapped_column(Text)
    history: Mapped[str | None] = mapped_column(Text)
    examination: Mapped[str | None] = mapped_column(Text)
    diagnosis: Mapped[str | None] = mapped_column(Text)
    advice: Mapped[str | None] = mapped_column(Text)
    follow_up_date: Mapped[date | None]
    notes: Mapped[str | None] = mapped_column(Text)
    # bp_systolic, bp_diastolic, pulse, temperature_c, weight_kg, height_cm, spo2, blood_sugar
    vitals: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    status: Mapped[ConsultationStatus] = mapped_column(
        _pg_enum(ConsultationStatus, "consultation_status"), server_default=text("'draft'")
    )
    finalized_at: Mapped[datetime | None]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), server_onupdate=FetchedValue()
    )


class ConsultationAddendum(Base):
    __tablename__ = "consultation_addenda"

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    consultation_id: Mapped[UUID] = mapped_column(
        ForeignKey("consultations.id", ondelete="CASCADE")
    )
    author_id: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    author_name: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Prescription(Base):
    __tablename__ = "prescriptions"

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    consultation_id: Mapped[UUID] = mapped_column(
        ForeignKey("consultations.id", ondelete="CASCADE"), unique=True
    )
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), server_onupdate=FetchedValue()
    )


class PrescriptionItem(Base):
    __tablename__ = "prescription_items"

    id: Mapped[UUID] = _uuid_pk()
    prescription_id: Mapped[UUID] = mapped_column(
        ForeignKey("prescriptions.id", ondelete="CASCADE")
    )
    medicine_name: Mapped[str] = mapped_column(Text)
    strength: Mapped[str | None] = mapped_column(Text)
    dosage_form: Mapped[str | None] = mapped_column(Text)
    dose: Mapped[str | None] = mapped_column(Text)
    route: Mapped[str | None] = mapped_column(Text)
    # Indian style, e.g. 1-0-1, 1-1-1, 0-0-1, SOS
    frequency: Mapped[str | None] = mapped_column(Text)
    # before_food | after_food | with_food | empty_stomach | bedtime | any
    timing: Mapped[str | None] = mapped_column(Text)
    duration_days: Mapped[int | None]
    instructions: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PatientReport(Base):
    __tablename__ = "patient_reports"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    consultation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("consultations.id", ondelete="SET NULL")
    )
    uploaded_by: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text)
    report_type: Mapped[ReportType] = mapped_column(_pg_enum(ReportType, "report_type"))
    report_date: Mapped[date | None]
    # {clinic_id}/{patient_id}/{report_id}.{ext} in the private `patient-reports` bucket
    storage_path: Mapped[str] = mapped_column(Text, unique=True)
    mime_type: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int]
    page_count: Mapped[int | None]
    # Large; deferred so list queries don't load it.
    extracted_text: Mapped[str | None] = deferred(mapped_column(Text))
    extraction_method: Mapped[ExtractionMethod | None] = mapped_column(
        _pg_enum(ExtractionMethod, "extraction_method")
    )
    ingestion_status: Mapped[IngestionStatus] = mapped_column(
        _pg_enum(IngestionStatus, "ingestion_status"), server_default=text("'pending'")
    )
    ingestion_error: Mapped[str | None] = mapped_column(Text)
    # Lab PDFs: the generated report of an order (is_generated) or the lab machine's own PDF.
    # Their content is indexed through the order's structured results, never separately.
    lab_order_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("lab_orders.id", ondelete="CASCADE")
    )
    is_generated: Mapped[bool] = mapped_column(server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), server_onupdate=FetchedValue()
    )


# ---------------------------------------------------------------------------
# Phase 2: RAG store, ingestion queue, chat, access log
# ---------------------------------------------------------------------------


class PatientRecordChunk(Base):
    __tablename__ = "patient_record_chunks"

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    source_type: Mapped[RecordSourceType] = mapped_column(
        _pg_enum(RecordSourceType, "record_source_type")
    )
    source_id: Mapped[UUID]
    source_date: Mapped[date | None]
    chunk_index: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'")
    )
    # Written with explicit SQL (see Vector); never loaded.
    embedding: Mapped[str] = deferred(mapped_column(Vector(EMBEDDING_DIM)))
    content_tsv: Mapped[str] = deferred(
        mapped_column(TSVECTOR, Computed("to_tsvector('english'::regconfig, content)"))
    )
    content_hash: Mapped[str] = mapped_column(Text)
    embedding_model: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    source_type: Mapped[RecordSourceType] = mapped_column(
        _pg_enum(RecordSourceType, "record_source_type")
    )
    source_id: Mapped[UUID]
    status: Mapped[JobStatus] = mapped_column(
        _pg_enum(JobStatus, "job_status"), server_default=text("'pending'")
    )
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    run_after: Mapped[datetime] = mapped_column(server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), server_onupdate=FetchedValue()
    )


class PatientChatSession(Base):
    __tablename__ = "patient_chat_sessions"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    doctor_id: Mapped[UUID | None] = mapped_column(ForeignKey("doctors.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), server_onupdate=FetchedValue()
    )


class PatientChatMessage(Base):
    __tablename__ = "patient_chat_messages"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("patient_chat_sessions.id", ondelete="CASCADE")
    )
    role: Mapped[ChatRole] = mapped_column(_pg_enum(ChatRole, "chat_role"))
    content: Mapped[str] = mapped_column(Text)
    # [{n, source_type, source_id, label, date, page}]
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'"))
    model: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    latency_ms: Mapped[int | None]
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PatientRecordAccessLog(Base):
    __tablename__ = "patient_record_access_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    action: Mapped[RecordAccessAction] = mapped_column(
        _pg_enum(RecordAccessAction, "record_access_action")
    )
    appointment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL")
    )
    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("patient_chat_sessions.id", ondelete="SET NULL")
    )
    report_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("patient_reports.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ---------------------------------------------------------------------------
# Phase 3: in-house lab
# ---------------------------------------------------------------------------


class LabTest(Base):
    __tablename__ = "lab_tests"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    category: Mapped[LabCategory] = mapped_column(_pg_enum(LabCategory, "lab_category"))
    sample_type: Mapped[LabSampleType] = mapped_column(_pg_enum(LabSampleType, "lab_sample_type"))
    container: Mapped[str | None] = mapped_column(Text)
    turnaround_hours: Mapped[int] = mapped_column(SmallInteger, server_default=text("24"))
    is_panel: Mapped[bool] = mapped_column(server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), server_onupdate=FetchedValue()
    )


class LabTestParameter(Base):
    __tablename__ = "lab_test_parameters"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[UUID] = _uuid_pk()
    test_id: Mapped[UUID] = mapped_column(ForeignKey("lab_tests.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[LabValueType] = mapped_column(
        _pg_enum(LabValueType, "lab_value_type"), server_default=text("'numeric'")
    )
    choices: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    decimals: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    delta_percent: Mapped[Decimal | None] = mapped_column(Numeric)
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), server_onupdate=FetchedValue()
    )


class LabReferenceRange(Base):
    __tablename__ = "lab_reference_ranges"

    id: Mapped[UUID] = _uuid_pk()
    parameter_id: Mapped[UUID] = mapped_column(
        ForeignKey("lab_test_parameters.id", ondelete="CASCADE")
    )
    sex: Mapped[LabRangeSex] = mapped_column(
        _pg_enum(LabRangeSex, "lab_range_sex"), server_default=text("'any'")
    )
    age_min_years: Mapped[int | None] = mapped_column(SmallInteger)
    age_max_years: Mapped[int | None] = mapped_column(SmallInteger)
    low: Mapped[Decimal | None] = mapped_column(Numeric)
    high: Mapped[Decimal | None] = mapped_column(Numeric)
    critical_low: Mapped[Decimal | None] = mapped_column(Numeric)
    critical_high: Mapped[Decimal | None] = mapped_column(Numeric)
    text_normal: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class LabOrder(Base):
    __tablename__ = "lab_orders"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    ordering_doctor_id: Mapped[UUID] = mapped_column(ForeignKey("doctors.id"))
    appointment_id: Mapped[UUID] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"))
    consultation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("consultations.id", ondelete="SET NULL")
    )
    order_number: Mapped[str] = mapped_column(Text)
    priority: Mapped[LabPriority] = mapped_column(
        _pg_enum(LabPriority, "lab_priority"), server_default=text("'routine'")
    )
    clinical_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[LabOrderStatus] = mapped_column(
        _pg_enum(LabOrderStatus, "lab_order_status"), server_default=text("'ordered'")
    )
    cancelled_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), server_onupdate=FetchedValue()
    )


class LabSample(Base):
    __tablename__ = "lab_samples"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    order_id: Mapped[UUID] = mapped_column(ForeignKey("lab_orders.id", ondelete="CASCADE"))
    sample_code: Mapped[str] = mapped_column(Text)
    sample_type: Mapped[LabSampleType] = mapped_column(_pg_enum(LabSampleType, "lab_sample_type"))
    container: Mapped[str | None] = mapped_column(Text)
    collected_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )
    collected_at: Mapped[datetime] = mapped_column(server_default=func.now())
    rejected_by: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    rejected_at: Mapped[datetime | None]
    rejected_reason: Mapped[str | None] = mapped_column(Text)


class LabOrderItem(Base):
    __tablename__ = "lab_order_items"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[UUID] = _uuid_pk()
    order_id: Mapped[UUID] = mapped_column(ForeignKey("lab_orders.id", ondelete="CASCADE"))
    test_id: Mapped[UUID] = mapped_column(ForeignKey("lab_tests.id"))
    test_code: Mapped[str] = mapped_column(Text)
    test_name: Mapped[str] = mapped_column(Text)
    status: Mapped[LabItemStatus] = mapped_column(
        _pg_enum(LabItemStatus, "lab_item_status"), server_default=text("'ordered'")
    )
    sample_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("lab_samples.id", ondelete="SET NULL")
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    return_comment: Mapped[str | None] = mapped_column(Text)
    entered_by: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    entered_at: Mapped[datetime | None]
    verified_by: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    verified_at: Mapped[datetime | None]
    released_by: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    released_at: Mapped[datetime | None]
    cancelled_reason: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), server_onupdate=FetchedValue()
    )


class LabResult(Base):
    __tablename__ = "lab_results"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[UUID] = _uuid_pk()
    order_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("lab_order_items.id", ondelete="CASCADE")
    )
    parameter_id: Mapped[UUID] = mapped_column(ForeignKey("lab_test_parameters.id"))
    parameter_code: Mapped[str] = mapped_column(Text)
    parameter_name: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[LabValueType] = mapped_column(_pg_enum(LabValueType, "lab_value_type"))
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric)
    value_text: Mapped[str | None] = mapped_column(Text)
    ref_low: Mapped[Decimal | None] = mapped_column(Numeric)
    ref_high: Mapped[Decimal | None] = mapped_column(Numeric)
    ref_critical_low: Mapped[Decimal | None] = mapped_column(Numeric)
    ref_critical_high: Mapped[Decimal | None] = mapped_column(Numeric)
    ref_text_normal: Mapped[str | None] = mapped_column(Text)
    range_label: Mapped[str | None] = mapped_column(Text)
    flag: Mapped[LabFlag | None] = mapped_column(_pg_enum(LabFlag, "lab_flag"))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    version: Mapped[int] = mapped_column(server_default=text("1"))
    is_current: Mapped[bool] = mapped_column(server_default=text("true"))
    amended_reason: Mapped[str | None] = mapped_column(Text)
    entered_by: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    entered_at: Mapped[datetime] = mapped_column(server_default=func.now())


class LabCriticalAlert(Base):
    __tablename__ = "lab_critical_alerts"
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[UUID] = _uuid_pk()
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    result_id: Mapped[UUID] = mapped_column(ForeignKey("lab_results.id", ondelete="CASCADE"))
    order_id: Mapped[UUID] = mapped_column(ForeignKey("lab_orders.id", ondelete="CASCADE"))
    patient_id: Mapped[UUID] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    doctor_id: Mapped[UUID] = mapped_column(ForeignKey("doctors.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    acknowledged_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )
    acknowledged_at: Mapped[datetime | None]
    note: Mapped[str | None] = mapped_column(Text)


class LabOrderEvent(Base):
    __tablename__ = "lab_order_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    clinic_id: Mapped[UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    order_id: Mapped[UUID] = mapped_column(ForeignKey("lab_orders.id", ondelete="CASCADE"))
    order_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("lab_order_items.id", ondelete="SET NULL")
    )
    event: Mapped[str] = mapped_column(Text)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
