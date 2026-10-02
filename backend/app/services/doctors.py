"""Doctors, weekly schedules and leave days."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment, Doctor, DoctorLeave, DoctorSchedule
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success
from app.services.booking.rules import INACTIVE_STATUSES

UPCOMING_LEAVE_DAYS = 60


@dataclass
class DoctorWithCalendar:
    doctor: Doctor
    schedules: list[DoctorSchedule] = field(default_factory=list)
    upcoming_leaves: list[DoctorLeave] = field(default_factory=list)


async def list_doctors(
    session: AsyncSession,
    clinic_id: UUID,
    today: date,
    *,
    include_inactive: bool = False,
    doctor_id: UUID | None = None,
) -> list[DoctorWithCalendar]:
    stmt = select(Doctor).where(Doctor.clinic_id == clinic_id)
    if not include_inactive:
        stmt = stmt.where(Doctor.is_active.is_(True))
    if doctor_id is not None:
        stmt = stmt.where(Doctor.id == doctor_id)
    doctors = list(await session.scalars(stmt.order_by(Doctor.full_name)))
    if not doctors:
        return []
    ids = [d.id for d in doctors]

    schedules: dict[UUID, list[DoctorSchedule]] = defaultdict(list)
    for schedule in await session.scalars(
        select(DoctorSchedule)
        .where(DoctorSchedule.doctor_id.in_(ids))
        .order_by(DoctorSchedule.weekday, DoctorSchedule.start_time)
    ):
        schedules[schedule.doctor_id].append(schedule)

    leaves: dict[UUID, list[DoctorLeave]] = defaultdict(list)
    for leave in await session.scalars(
        select(DoctorLeave)
        .where(
            DoctorLeave.doctor_id.in_(ids),
            DoctorLeave.leave_date >= today,
            DoctorLeave.leave_date <= today + timedelta(days=UPCOMING_LEAVE_DAYS),
        )
        .order_by(DoctorLeave.leave_date)
    ):
        leaves[leave.doctor_id].append(leave)

    return [DoctorWithCalendar(d, schedules[d.id], leaves[d.id]) for d in doctors]


async def get_doctor(session: AsyncSession, clinic_id: UUID, doctor_id: UUID) -> Doctor | None:
    return await session.scalar(
        select(Doctor).where(Doctor.id == doctor_id, Doctor.clinic_id == clinic_id)
    )


async def create_doctor(session: AsyncSession, clinic_id: UUID, values: dict[str, Any]) -> Doctor:
    doctor = Doctor(clinic_id=clinic_id, **values)
    session.add(doctor)
    await session.commit()
    return doctor


async def update_doctor(
    session: AsyncSession, clinic_id: UUID, doctor_id: UUID, changes: dict[str, Any]
) -> BookingResult[Doctor]:
    doctor = await get_doctor(session, clinic_id, doctor_id)
    if doctor is None:
        return failure(BookingErrorCode.NOT_FOUND, "Doctor not found.")
    for name, value in changes.items():
        setattr(doctor, name, value)
    await session.commit()
    return success(doctor)


async def replace_schedules(
    session: AsyncSession,
    clinic_id: UUID,
    doctor_id: UUID,
    shifts: list[tuple[int, time, time]],
) -> BookingResult[list[DoctorSchedule]]:
    """Replace the doctor's whole weekly schedule. Existing appointments are left untouched."""
    if await get_doctor(session, clinic_id, doctor_id) is None:
        return failure(BookingErrorCode.NOT_FOUND, "Doctor not found.")
    await session.execute(delete(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor_id))
    rows = [
        DoctorSchedule(
            clinic_id=clinic_id, doctor_id=doctor_id, weekday=wd, start_time=start, end_time=end
        )
        for wd, start, end in sorted(shifts)
    ]
    session.add_all(rows)
    await session.commit()
    return success(rows)


@dataclass(frozen=True)
class LeaveCreated:
    leave: DoctorLeave
    affected_appointments: int


async def add_leave(
    session: AsyncSession,
    clinic_id: UUID,
    doctor_id: UUID,
    leave_date: date,
    reason: str | None,
) -> BookingResult[LeaveCreated]:
    if await get_doctor(session, clinic_id, doctor_id) is None:
        return failure(BookingErrorCode.NOT_FOUND, "Doctor not found.")
    leave = DoctorLeave(
        clinic_id=clinic_id, doctor_id=doctor_id, leave_date=leave_date, reason=reason
    )
    session.add(leave)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return failure(BookingErrorCode.ALREADY_EXISTS, "Leave is already recorded for that day.")
    affected = await session.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == leave_date,
            Appointment.status.not_in(INACTIVE_STATUSES),
        )
    )
    await session.commit()
    return success(LeaveCreated(leave, affected or 0))


async def delete_leave(session: AsyncSession, clinic_id: UUID, leave_id: UUID) -> bool:
    result = await session.execute(
        delete(DoctorLeave)
        .where(DoctorLeave.id == leave_id, DoctorLeave.clinic_id == clinic_id)
        .returning(DoctorLeave.id)
    )
    deleted = result.first() is not None
    await session.commit()
    return deleted
