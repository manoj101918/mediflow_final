import uuid
from datetime import date, datetime, time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AppointmentSource, AppointmentStatus
from app.services.booking import (
    BookingErrorCode,
    NewAppointment,
    create_appointment,
    get_available_slots,
    update_appointment_status,
)
from tests.booking_utils import DAY, IST, NEXT_DAY, NOW, ist
from tests.conftest import ClinicFixture

Sessions = async_sessionmaker[AsyncSession]


async def _starts(
    sessionmaker: Sessions,
    clinic: ClinicFixture,
    doctor_id: uuid.UUID,
    *,
    day: date = DAY,
    now: datetime = NOW,
) -> list[str]:
    """Free slot start times as HH:MM (IST)."""
    async with sessionmaker() as session:
        result = await get_available_slots(session, clinic.id, doctor_id, day, now=now)
    return [s.starts_at.astimezone(IST).strftime("%H:%M") for s in result.unwrap().slots]


async def test_slots_cover_every_shift(sessionmaker: Sessions, clinic: ClinicFixture) -> None:
    doctor = await clinic.add_doctor(
        windows=((time(9), time(10)), (time(17), time(17, 30))), slot_minutes=15
    )
    assert await _starts(sessionmaker, clinic, doctor, now=NOW) == [
        "09:00", "09:15", "09:30", "09:45", "17:00", "17:15",
    ]  # fmt: skip


async def test_slot_must_fit_inside_window(sessionmaker: Sessions, clinic: ClinicFixture) -> None:
    doctor = await clinic.add_doctor(windows=((time(9), time(9, 40)),), slot_minutes=15)
    # 09:30 would end at 09:45, after the shift ends.
    assert await _starts(sessionmaker, clinic, doctor, now=NOW) == ["09:00", "09:15"]


async def test_no_slots_on_unscheduled_weekday(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    doctor = await clinic.add_doctor(weekdays=(0,))
    assert await _starts(sessionmaker, clinic, doctor, day=NEXT_DAY, now=NOW) == []


async def test_leave_day_has_no_slots(sessionmaker: Sessions, clinic: ClinicFixture) -> None:
    doctor = await clinic.add_doctor()
    await clinic.add_leave(doctor, DAY)
    async with sessionmaker() as session:
        result = (await get_available_slots(session, clinic.id, doctor, DAY, now=NOW)).unwrap()
    assert result.on_leave is True
    assert result.slots == []


async def test_slots_already_started_are_dropped(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    doctor = await clinic.add_doctor(windows=((time(9), time(10)),))
    assert await _starts(sessionmaker, clinic, doctor, now=ist(9, 20)) == ["09:30", "09:45"]


async def test_booked_slots_are_hidden_until_cancelled(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    doctor = await clinic.add_doctor(windows=((time(9), time(10)),))
    patient = await clinic.add_patient()
    actor = await clinic.staff()
    async with sessionmaker() as session:
        booked = await create_appointment(
            session,
            NewAppointment(patient, doctor, ist(9, 15), AppointmentSource.PHONE),
            actor,
            now=NOW,
        )
    assert booked.ok
    assert await _starts(sessionmaker, clinic, doctor, now=NOW) == ["09:00", "09:30", "09:45"]

    async with sessionmaker() as session:
        cancelled = await update_appointment_status(
            session, booked.unwrap().id, AppointmentStatus.CANCELLED, actor
        )
    assert cancelled.ok
    assert await _starts(sessionmaker, clinic, doctor, now=NOW) == [
        "09:00", "09:15", "09:30", "09:45",
    ]  # fmt: skip


async def test_unknown_or_inactive_doctor(sessionmaker: Sessions, clinic: ClinicFixture) -> None:
    inactive = await clinic.add_doctor(active=False)
    async with sessionmaker() as session:
        for doctor_id in (inactive, uuid.uuid4()):
            result = await get_available_slots(session, clinic.id, doctor_id, DAY, now=NOW)
            assert result.code is BookingErrorCode.NOT_FOUND
