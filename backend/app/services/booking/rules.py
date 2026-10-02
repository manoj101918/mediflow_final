"""Scheduling rules shared by slot listing, booking and rescheduling."""

from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppointmentStatus, Clinic, Doctor, DoctorLeave, DoctorSchedule
from app.services.booking.timeutil import DEFAULT_TIMEZONE, clinic_tz, local_datetime

# Appointments in these statuses no longer hold their time slot (mirrors the DB constraint).
INACTIVE_STATUSES = frozenset({AppointmentStatus.CANCELLED, AppointmentStatus.NO_SHOW})

# A booking may start this long before "now" (the receptionist is mid-way through the form).
PAST_GRACE = timedelta(minutes=5)

Window = tuple[time, time]


async def clinic_timezone(session: AsyncSession, clinic_id: UUID) -> ZoneInfo:
    name = await session.scalar(select(Clinic.timezone).where(Clinic.id == clinic_id))
    return clinic_tz(name or DEFAULT_TIMEZONE)


async def active_doctor(session: AsyncSession, clinic_id: UUID, doctor_id: UUID) -> Doctor | None:
    return await session.scalar(
        select(Doctor).where(
            Doctor.id == doctor_id, Doctor.clinic_id == clinic_id, Doctor.is_active.is_(True)
        )
    )


async def is_on_leave(session: AsyncSession, doctor_id: UUID, day: date) -> bool:
    return bool(
        await session.scalar(
            select(
                exists().where(DoctorLeave.doctor_id == doctor_id, DoctorLeave.leave_date == day)
            )
        )
    )


async def schedule_windows(session: AsyncSession, doctor_id: UUID, day: date) -> list[Window]:
    rows = await session.execute(
        select(DoctorSchedule.start_time, DoctorSchedule.end_time)
        .where(DoctorSchedule.doctor_id == doctor_id, DoctorSchedule.weekday == day.weekday())
        .order_by(DoctorSchedule.start_time)
    )
    return [(start, end) for start, end in rows]


def slot_grid(
    day: date, windows: list[Window], slot_minutes: int, tz: ZoneInfo
) -> list[tuple[datetime, datetime]]:
    """Every slot that fits entirely inside one of the schedule windows."""
    step = timedelta(minutes=slot_minutes)
    slots: list[tuple[datetime, datetime]] = []
    for start, end in windows:
        cursor = local_datetime(day, start, tz)
        window_end = local_datetime(day, end, tz)
        while cursor + step <= window_end:
            slots.append((cursor, cursor + step))
            cursor += step
    return slots


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open [start, end) overlap, matching tstzrange(..., '[)') in the DB constraint."""
    return a_start < b_end and b_start < a_end
