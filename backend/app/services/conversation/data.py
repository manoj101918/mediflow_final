"""Read-only lookups for the engine. Everything is returned as plain values."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment, AppointmentStatus, Clinic, Doctor, Patient
from app.services.booking import get_available_slots
from app.services.booking.timeutil import clinic_tz

BOOKING_DAYS = 7
MAX_FAMILY = 9  # list rows: up to 9 people + "Someone else"


@dataclass(frozen=True)
class ClinicInfo:
    name: str
    tz: ZoneInfo


@dataclass(frozen=True)
class DoctorInfo:
    id: UUID
    name: str
    specialization: str


@dataclass(frozen=True)
class PatientInfo:
    id: UUID
    name: str


@dataclass(frozen=True)
class UpcomingInfo:
    id: UUID
    patient_name: str
    doctor_id: UUID
    doctor_name: str
    starts_at: datetime
    status: AppointmentStatus
    token_number: int


async def clinic_info(session: AsyncSession, clinic_id: UUID) -> ClinicInfo:
    row = (
        await session.execute(select(Clinic.name, Clinic.timezone).where(Clinic.id == clinic_id))
    ).one()
    return ClinicInfo(name=row.name, tz=clinic_tz(row.timezone))


async def active_doctors(session: AsyncSession, clinic_id: UUID) -> list[DoctorInfo]:
    rows = await session.execute(
        select(Doctor.id, Doctor.full_name, Doctor.specialization)
        .where(Doctor.clinic_id == clinic_id, Doctor.is_active.is_(True))
        .order_by(Doctor.full_name)
        .limit(10)
    )
    return [DoctorInfo(id=r.id, name=r.full_name, specialization=r.specialization) for r in rows]


async def doctor(session: AsyncSession, clinic_id: UUID, doctor_id: UUID) -> DoctorInfo | None:
    row = (
        await session.execute(
            select(Doctor.id, Doctor.full_name, Doctor.specialization).where(
                Doctor.id == doctor_id, Doctor.clinic_id == clinic_id, Doctor.is_active.is_(True)
            )
        )
    ).first()
    return (
        DoctorInfo(id=row.id, name=row.full_name, specialization=row.specialization)
        if row
        else None
    )


async def family(session: AsyncSession, clinic_id: UUID, phone: str) -> list[PatientInfo]:
    """Patients registered with this phone (a family often shares one number)."""
    rows = await session.execute(
        select(Patient.id, Patient.full_name)
        .where(Patient.clinic_id == clinic_id, Patient.phone == phone)
        .order_by(Patient.created_at)
        .limit(MAX_FAMILY)
    )
    return [PatientInfo(id=r.id, name=r.full_name) for r in rows]


async def patient_name(session: AsyncSession, clinic_id: UUID, patient_id: UUID) -> str | None:
    return await session.scalar(
        select(Patient.full_name).where(Patient.id == patient_id, Patient.clinic_id == clinic_id)
    )


async def free_slots(
    session: AsyncSession, clinic_id: UUID, doctor_id: UUID, day: date, now: datetime
) -> list[datetime]:
    result = await get_available_slots(session, clinic_id, doctor_id, day, now=now)
    return [s.starts_at for s in result.unwrap().slots] if result.ok else []


async def open_days(
    session: AsyncSession, clinic_id: UUID, doctor_id: UUID, today: date, now: datetime
) -> list[tuple[date, int]]:
    """Days in the next week with at least one free slot, with their free-slot count."""
    days: list[tuple[date, int]] = []
    for offset in range(BOOKING_DAYS):
        day = today + timedelta(days=offset)
        count = len(await free_slots(session, clinic_id, doctor_id, day, now))
        if count:
            days.append((day, count))
    return days


async def upcoming(
    session: AsyncSession, clinic_id: UUID, phone: str, now: datetime
) -> list[UpcomingInfo]:
    rows = await session.execute(
        select(
            Appointment.id,
            Patient.full_name,
            Appointment.doctor_id,
            Doctor.full_name.label("doctor_name"),
            Appointment.starts_at,
            Appointment.status,
            Appointment.token_number,
        )
        .join(Patient, Patient.id == Appointment.patient_id)
        .join(Doctor, Doctor.id == Appointment.doctor_id)
        .where(
            Appointment.clinic_id == clinic_id,
            Patient.phone == phone,
            Appointment.starts_at > now,
            Appointment.status.in_(
                (AppointmentStatus.PENDING_CONFIRMATION, AppointmentStatus.SCHEDULED)
            ),
        )
        .order_by(Appointment.starts_at)
        .limit(10)
    )
    return [
        UpcomingInfo(
            id=r.id,
            patient_name=r.full_name,
            doctor_id=r.doctor_id,
            doctor_name=r.doctor_name,
            starts_at=r.starts_at,
            status=r.status,
            token_number=r.token_number,
        )
        for r in rows
    ]
