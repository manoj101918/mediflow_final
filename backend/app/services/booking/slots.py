from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment
from app.services.booking import rules
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success
from app.services.booking.timeutil import day_bounds, utcnow


@dataclass(frozen=True)
class Slot:
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class DaySlots:
    doctor_id: UUID
    date: date
    slot_minutes: int
    on_leave: bool
    slots: list[Slot]


async def get_available_slots(
    session: AsyncSession,
    clinic_id: UUID,
    doctor_id: UUID,
    day: date,
    now: datetime | None = None,
) -> BookingResult[DaySlots]:
    """Free slots for a doctor on a clinic-local day.

    Schedule windows for that weekday, cut into `default_slot_minutes` slots, minus leave days,
    minus slots overlapping a live appointment, minus slots that already started.
    """
    doctor = await rules.active_doctor(session, clinic_id, doctor_id)
    if doctor is None:
        return failure(BookingErrorCode.NOT_FOUND, "Doctor not found.")

    def result(slots: list[Slot], *, on_leave: bool = False) -> BookingResult[DaySlots]:
        return success(
            DaySlots(
                doctor_id=doctor_id,
                date=day,
                slot_minutes=doctor.default_slot_minutes,
                on_leave=on_leave,
                slots=slots,
            )
        )

    if await rules.is_on_leave(session, doctor_id, day):
        return result([], on_leave=True)

    tz = await rules.clinic_timezone(session, clinic_id)
    windows = await rules.schedule_windows(session, doctor_id, day)
    grid = rules.slot_grid(day, windows, doctor.default_slot_minutes, tz)
    if not grid:
        return result([])

    day_start, day_end = day_bounds(day, tz)
    booked = await session.execute(
        select(Appointment.starts_at, Appointment.ends_at).where(
            Appointment.doctor_id == doctor_id,
            Appointment.starts_at < day_end,
            Appointment.ends_at > day_start,
            Appointment.status.not_in(rules.INACTIVE_STATUSES),
        )
    )
    busy = [(start, end) for start, end in booked]

    current = now or utcnow()
    free = [
        Slot(start, end)
        for start, end in grid
        if start >= current and not any(rules.overlaps(start, end, b, e) for b, e in busy)
    ]
    return result(free)
