import itertools
import uuid
from datetime import time

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Appointment, AppointmentSource, AppointmentStatus, UserRole
from app.services.booking import (
    ALLOWED_TRANSITIONS,
    Actor,
    BookingErrorCode,
    BookingResult,
    NewAppointment,
    StaffActor,
    approve_appointment,
    can_transition,
    create_appointment,
    reject_appointment,
    reschedule_appointment,
    update_appointment_status,
)
from tests.booking_utils import DAY, NEXT_DAY, NOW, ist
from tests.conftest import ClinicFixture

Sessions = async_sessionmaker[AsyncSession]
S = AppointmentStatus

EXPECTED = {
    (S.PENDING_CONFIRMATION, S.SCHEDULED),
    (S.PENDING_CONFIRMATION, S.CANCELLED),
    (S.SCHEDULED, S.CHECKED_IN),
    (S.SCHEDULED, S.CANCELLED),
    (S.SCHEDULED, S.NO_SHOW),
    (S.CHECKED_IN, S.IN_CONSULTATION),
    (S.CHECKED_IN, S.CANCELLED),
    (S.CHECKED_IN, S.NO_SHOW),
    (S.IN_CONSULTATION, S.COMPLETED),
}


@pytest.mark.parametrize(("current", "target"), list(itertools.product(S, S)))
def test_transition_map(current: AppointmentStatus, target: AppointmentStatus) -> None:
    assert can_transition(current, target) is ((current, target) in EXPECTED)


def test_terminal_states_have_no_exits() -> None:
    for terminal in (S.COMPLETED, S.CANCELLED, S.NO_SHOW):
        assert ALLOWED_TRANSITIONS[terminal] == frozenset()


async def _appointment(
    sessionmaker: Sessions,
    clinic: ClinicFixture,
    actor: Actor,
    doctor: uuid.UUID,
    at: tuple[int, int] = (9, 0),
    source: AppointmentSource = AppointmentSource.PHONE,
) -> Appointment:
    patient = await clinic.add_patient(f"Patient {uuid.uuid4().hex[:6]}")
    async with sessionmaker() as session:
        result = await create_appointment(
            session, NewAppointment(patient, doctor, ist(*at), source), actor, now=NOW
        )
    return result.unwrap()


async def _set(
    sessionmaker: Sessions, appointment_id: uuid.UUID, target: AppointmentStatus, actor: Actor
) -> BookingResult[Appointment]:
    async with sessionmaker() as session:
        return await update_appointment_status(session, appointment_id, target, actor)


async def test_front_desk_runs_the_full_visit(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    desk, doctor = await clinic.staff(), await clinic.add_doctor()
    appt = await _appointment(sessionmaker, clinic, desk, doctor)
    for target in (S.CHECKED_IN, S.IN_CONSULTATION, S.COMPLETED):
        result = await _set(sessionmaker, appt.id, target, desk)
        assert result.ok, result.message
        assert result.unwrap().status is target
    again = await _set(sessionmaker, appt.id, S.CANCELLED, desk)
    assert again.code is BookingErrorCode.INVALID_TRANSITION


async def test_invalid_jump_is_rejected(sessionmaker: Sessions, clinic: ClinicFixture) -> None:
    desk, doctor = await clinic.staff(), await clinic.add_doctor()
    appt = await _appointment(sessionmaker, clinic, desk, doctor)
    result = await _set(sessionmaker, appt.id, S.COMPLETED, desk)
    assert result.code is BookingErrorCode.INVALID_TRANSITION


async def test_doctor_can_only_start_and_complete_own(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    desk = await clinic.staff()
    doc = await clinic.staff(UserRole.DOCTOR)
    assert doc.doctor_id is not None
    # Give the linked doctor a schedule so the front desk can book them.
    other_doctor = await clinic.add_doctor(name="Dr. Someone Else")
    async with sessionmaker() as session:
        await session.execute(
            text(
                "insert into public.doctor_schedules (clinic_id, doctor_id, weekday, start_time, "
                "end_time) values (:cid, :did, 0, '09:00', '10:00')"
            ),
            {"cid": clinic.id, "did": doc.doctor_id},
        )
        await session.commit()

    mine = await _appointment(sessionmaker, clinic, desk, doc.doctor_id)
    theirs = await _appointment(sessionmaker, clinic, desk, other_doctor)

    # Check-in is the front desk's job.
    assert (await _set(sessionmaker, mine.id, S.CHECKED_IN, doc)).code is (
        BookingErrorCode.FORBIDDEN
    )
    assert (await _set(sessionmaker, mine.id, S.CHECKED_IN, desk)).ok
    assert (await _set(sessionmaker, mine.id, S.IN_CONSULTATION, doc)).ok
    assert (await _set(sessionmaker, mine.id, S.COMPLETED, doc)).ok

    # Another doctor's appointment is invisible to this doctor.
    assert (await _set(sessionmaker, theirs.id, S.CHECKED_IN, desk)).ok
    assert (await _set(sessionmaker, theirs.id, S.IN_CONSULTATION, doc)).code is (
        BookingErrorCode.NOT_FOUND
    )


async def test_bots_cannot_change_status(sessionmaker: Sessions, clinic: ClinicFixture) -> None:
    desk, doctor = await clinic.staff(), await clinic.add_doctor()
    appt = await _appointment(sessionmaker, clinic, desk, doctor)
    result = await _set(sessionmaker, appt.id, S.CANCELLED, clinic.system())
    assert result.code is BookingErrorCode.FORBIDDEN


async def test_other_clinic_cannot_touch_appointment(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    desk, doctor = await clinic.staff(), await clinic.add_doctor()
    appt = await _appointment(sessionmaker, clinic, desk, doctor)
    outsider = StaffActor(desk.user_id, UserRole.RECEPTIONIST, uuid.uuid4())
    assert (await _set(sessionmaker, appt.id, S.CANCELLED, outsider)).code is (
        BookingErrorCode.NOT_FOUND
    )


async def test_approve_and_reject_pending(sessionmaker: Sessions, clinic: ClinicFixture) -> None:
    desk, doctor = await clinic.staff(), await clinic.add_doctor()
    bot = clinic.system("voice")
    first = await _appointment(sessionmaker, clinic, bot, doctor, (9, 0), AppointmentSource.VOICE)
    second = await _appointment(sessionmaker, clinic, bot, doctor, (9, 15), AppointmentSource.VOICE)
    assert first.status is S.PENDING_CONFIRMATION

    async with sessionmaker() as session:
        approved = await approve_appointment(session, first.id, desk)
    assert approved.ok and approved.unwrap().status is S.SCHEDULED

    async with sessionmaker() as session:
        rejected = await reject_appointment(session, second.id, desk, "Doctor unavailable")
    assert rejected.ok and rejected.unwrap().status is S.CANCELLED

    # Approving something that is no longer pending is an invalid transition.
    async with sessionmaker() as session:
        again = await approve_appointment(session, first.id, desk)
    assert again.code is BookingErrorCode.INVALID_TRANSITION


async def test_reschedule_same_day_keeps_token(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    desk, doctor = await clinic.staff(), await clinic.add_doctor()
    appt = await _appointment(sessionmaker, clinic, desk, doctor)
    async with sessionmaker() as session:
        moved = await reschedule_appointment(session, appt.id, ist(9, 45), desk, now=NOW)
    assert moved.ok, moved.message
    assert moved.unwrap().starts_at == ist(9, 45)
    assert moved.unwrap().ends_at == ist(10)
    assert moved.unwrap().token_number == appt.token_number


async def test_reschedule_to_another_day_gets_new_token(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    desk = await clinic.staff()
    doctor = await clinic.add_doctor(weekdays=(0, 1))
    await _appointment(sessionmaker, clinic, desk, doctor, (9, 0))
    appt = await _appointment(sessionmaker, clinic, desk, doctor, (9, 15))
    async with sessionmaker() as session:
        # Tuesday already has token 1.
        patient = await clinic.add_patient("Tuesday Patient")
        await create_appointment(
            session,
            NewAppointment(patient, doctor, ist(9, 0, NEXT_DAY), AppointmentSource.PHONE),
            desk,
            now=NOW,
        )
    async with sessionmaker() as session:
        moved = await reschedule_appointment(session, appt.id, ist(9, 30, NEXT_DAY), desk, now=NOW)
    assert moved.ok, moved.message
    assert moved.unwrap().appointment_date == NEXT_DAY
    assert moved.unwrap().token_number == 2


async def test_reschedule_conflicts_and_rules(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    desk = await clinic.staff()
    doctor = await clinic.add_doctor(windows=((time(9), time(10)),))
    a = await _appointment(sessionmaker, clinic, desk, doctor, (9, 0))
    b = await _appointment(sessionmaker, clinic, desk, doctor, (9, 15))

    async def move(
        appt_id: uuid.UUID, hour: int, minute: int = 0, actor: Actor = desk
    ) -> BookingResult[Appointment]:
        async with sessionmaker() as session:
            return await reschedule_appointment(session, appt_id, ist(hour, minute), actor, now=NOW)

    assert (await move(a.id, 9, 15)).code is BookingErrorCode.SLOT_TAKEN
    assert (await move(a.id, 12)).code is BookingErrorCode.OUTSIDE_SCHEDULE
    assert (await move(a.id, 9)).code is BookingErrorCode.VALIDATION
    assert (await move(a.id, 9, 30, clinic.system())).code is BookingErrorCode.FORBIDDEN

    await _set(sessionmaker, b.id, S.CHECKED_IN, desk)
    assert (await move(b.id, 9, 45)).code is BookingErrorCode.INVALID_TRANSITION

    await clinic.add_leave(doctor, DAY)
    assert (await move(a.id, 9, 30)).code is BookingErrorCode.DOCTOR_ON_LEAVE
