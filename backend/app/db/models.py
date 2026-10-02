"""SQLAlchemy models mirroring supabase/migrations exactly.

The schema is owned by the SQL migrations (applied via Supabase MCP); these models never
create or alter tables. Constraints that matter to the service layer (e.g. the appointments
no-overlap exclusion constraint) are enforced by the database and surfaced as errors.
"""

import enum
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UserRole(enum.StrEnum):
    ADMIN = "admin"
    RECEPTIONIST = "receptionist"
    DOCTOR = "doctor"


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
