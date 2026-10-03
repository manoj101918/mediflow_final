"""Bots may cancel or move only upcoming appointments of their verified sender's patients."""

from datetime import datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Appointment, AppointmentEvent, AppointmentStatus
from app.services.booking import (
    BookingErrorCode,
    SystemActor,
    reschedule_appointment,
    update_appointment_status,
)
from tests.api_utils import EVERY_DAY, IST, TODAY, TOMORROW
from tests.conftest import ClinicFixture

Sessions = async_sessionmaker[AsyncSession]
S = AppointmentStatus
PHONE = "+919811122233"


def tomorrow_at(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(TOMORROW, time(hour, minute), tzinfo=IST)


async def _setup(clinic: ClinicFixture, status: str = "scheduled") -> tuple[SystemActor, UUID]:
    doctor = await clinic.add_doctor(windows=((time(9), time(11)),), weekdays=EVERY_DAY)
    patient = await clinic.add_patient("Ravi Kumar", PHONE)
    appointment = await clinic.add_appointment(
        doctor, patient, status=status, starts_at=tomorrow_at(9)
    )
    return SystemActor(channel="whatsapp", clinic_id=clinic.id, phone_e164=PHONE), appointment


async def test_bot_cancels_own_upcoming_appointment(
    clinic: ClinicFixture, sessionmaker: Sessions
) -> None:
    actor, appointment_id = await _setup(clinic)
    async with sessionmaker() as session:
        result = await update_appointment_status(session, appointment_id, S.CANCELLED, actor)
        assert result.ok, result.message
    async with sessionmaker() as session:
        event = await session.scalar(
            select(AppointmentEvent).where(AppointmentEvent.appointment_id == appointment_id)
        )
        assert event is not None
        assert (event.from_status, event.to_status, event.channel) == (
            S.SCHEDULED,
            S.CANCELLED,
            "whatsapp",
        )


async def test_bot_without_phone_cannot_change_status(
    clinic: ClinicFixture, sessionmaker: Sessions
) -> None:
    _, appointment_id = await _setup(clinic)
    async with sessionmaker() as session:
        result = await update_appointment_status(
            session, appointment_id, S.CANCELLED, clinic.system()
        )
    assert result.code is BookingErrorCode.FORBIDDEN


async def test_bot_cannot_touch_other_phones_or_approve(
    clinic: ClinicFixture, sessionmaker: Sessions
) -> None:
    actor, appointment_id = await _setup(clinic, status="pending_confirmation")
    stranger = SystemActor(channel="whatsapp", clinic_id=clinic.id, phone_e164="+919800099999")
    async with sessionmaker() as session:
        missing = await update_appointment_status(session, appointment_id, S.CANCELLED, stranger)
        approve = await update_appointment_status(session, appointment_id, S.SCHEDULED, actor)
        moved = await reschedule_appointment(session, appointment_id, tomorrow_at(9, 30), stranger)
    assert missing.code is BookingErrorCode.NOT_FOUND
    assert approve.code is BookingErrorCode.FORBIDDEN
    assert moved.code is BookingErrorCode.NOT_FOUND


async def test_bot_cannot_cancel_past_or_checked_in(
    clinic: ClinicFixture, sessionmaker: Sessions
) -> None:
    doctor = await clinic.add_doctor(weekdays=EVERY_DAY)
    patient = await clinic.add_patient("Ravi Kumar", PHONE)
    past = await clinic.add_appointment(
        doctor,
        patient,
        status="scheduled",
        starts_at=datetime.combine(TODAY - timedelta(days=1), time(9), tzinfo=IST),
    )
    checked_in = await clinic.add_appointment(
        doctor, patient, status="checked_in", starts_at=tomorrow_at(9)
    )
    actor = SystemActor(channel="voice", clinic_id=clinic.id, phone_e164=PHONE)
    async with sessionmaker() as session:
        for appointment_id in (past, checked_in):
            result = await update_appointment_status(session, appointment_id, S.CANCELLED, actor)
            assert result.code is BookingErrorCode.INVALID_TRANSITION


async def test_bot_reschedule_goes_back_to_pending(
    clinic: ClinicFixture, sessionmaker: Sessions
) -> None:
    actor, appointment_id = await _setup(clinic)
    async with sessionmaker() as session:
        result = await reschedule_appointment(session, appointment_id, tomorrow_at(10), actor)
        assert result.ok, result.message
    async with sessionmaker() as session:
        appointment = await session.get(Appointment, appointment_id)
        assert appointment is not None
        assert appointment.status is S.PENDING_CONFIRMATION
        assert appointment.starts_at == tomorrow_at(10)


async def test_bot_cannot_squeeze_in(clinic: ClinicFixture, sessionmaker: Sessions) -> None:
    actor, appointment_id = await _setup(clinic)
    async with sessionmaker() as session:
        result = await reschedule_appointment(
            session, appointment_id, tomorrow_at(12), actor, squeeze_in=True
        )
    assert result.code is BookingErrorCode.FORBIDDEN
