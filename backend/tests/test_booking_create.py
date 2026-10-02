import asyncio
import uuid
from datetime import date, time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    ActorType,
    Appointment,
    AppointmentEvent,
    AppointmentSource,
    AppointmentStatus,
    UserRole,
)
from app.services.booking import (
    BookingErrorCode,
    BookingResult,
    NewAppointment,
    StaffActor,
    SystemActor,
    create_appointment,
    update_appointment_status,
)
from app.services.booking.create import SQUEEZE_IN_NOTE
from tests.booking_utils import DAY, NEXT_DAY, NOW, ist
from tests.conftest import ClinicFixture

Sessions = async_sessionmaker[AsyncSession]
PHONE = AppointmentSource.PHONE


async def _book(
    sessionmaker: Sessions,
    actor: StaffActor | SystemActor,
    patient: uuid.UUID,
    doctor: uuid.UUID,
    hour: int,
    minute: int = 0,
    *,
    day: date = DAY,
    source: AppointmentSource = PHONE,
    squeeze_in: bool = False,
    notes: str | None = None,
    reason_for_visit: str | None = None,
    external_ref: str | None = None,
) -> BookingResult[Appointment]:
    data = NewAppointment(
        patient_id=patient,
        doctor_id=doctor,
        starts_at=ist(hour, minute, day),
        source=source,
        reason_for_visit=reason_for_visit,
        notes=notes,
        squeeze_in=squeeze_in,
        external_ref=external_ref,
    )
    async with sessionmaker() as session:
        return await create_appointment(session, data, actor, now=NOW)


async def _events(sessionmaker: Sessions, appointment_id: uuid.UUID) -> list[AppointmentEvent]:
    async with sessionmaker() as session:
        rows = await session.scalars(
            select(AppointmentEvent)
            .where(AppointmentEvent.appointment_id == appointment_id)
            .order_by(AppointmentEvent.id)
        )
        return list(rows)


async def test_staff_booking_is_scheduled_with_token_and_event(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    doctor, patient, actor = (
        await clinic.add_doctor(),
        await clinic.add_patient(),
        await clinic.staff(),
    )
    result = await _book(sessionmaker, actor, patient, doctor, 9, reason_for_visit="Fever")
    assert result.ok, result.message
    appt = result.unwrap()
    assert appt.status is AppointmentStatus.SCHEDULED
    assert appt.token_number == 1
    assert appt.appointment_date == DAY
    assert appt.ends_at == ist(9, 15)
    assert appt.created_by == actor.user_id

    [event] = await _events(sessionmaker, appt.id)
    assert (event.from_status, event.to_status) == (None, AppointmentStatus.SCHEDULED)
    assert (event.actor_type, event.channel, event.changed_by) == (
        ActorType.USER,
        "dashboard",
        actor.user_id,
    )


async def test_bot_booking_is_pending_confirmation(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    doctor, patient = await clinic.add_doctor(), await clinic.add_patient()
    bot = clinic.system("whatsapp")
    result = await _book(
        sessionmaker,
        bot,
        patient,
        doctor,
        9,
        source=AppointmentSource.WHATSAPP,
        external_ref="wa-1",
    )
    assert result.ok, result.message
    appt = result.unwrap()
    assert appt.status is AppointmentStatus.PENDING_CONFIRMATION
    assert appt.created_by is None
    [event] = await _events(sessionmaker, appt.id)
    assert (event.actor_type, event.channel) == (ActorType.SYSTEM, "whatsapp")


async def test_bot_source_must_match_channel(sessionmaker: Sessions, clinic: ClinicFixture) -> None:
    doctor, patient = await clinic.add_doctor(), await clinic.add_patient()
    result = await _book(sessionmaker, clinic.system("voice"), patient, doctor, 9, source=PHONE)
    assert result.code is BookingErrorCode.VALIDATION


async def test_duplicate_external_ref_is_already_exists(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    doctor, patient = await clinic.add_doctor(), await clinic.add_patient()
    bot = clinic.system("whatsapp")
    wa = AppointmentSource.WHATSAPP
    assert (await _book(sessionmaker, bot, patient, doctor, 9, source=wa, external_ref="dup")).ok
    again = await _book(sessionmaker, bot, patient, doctor, 9, 30, source=wa, external_ref="dup")
    assert again.code is BookingErrorCode.ALREADY_EXISTS


async def test_double_booking_is_slot_taken(sessionmaker: Sessions, clinic: ClinicFixture) -> None:
    doctor, actor = await clinic.add_doctor(), await clinic.staff()
    p1, p2 = await clinic.add_patient("A One"), await clinic.add_patient("B Two", "+919800000002")
    assert (await _book(sessionmaker, actor, p1, doctor, 9)).ok
    second = await _book(sessionmaker, actor, p2, doctor, 9)
    assert second.code is BookingErrorCode.SLOT_TAKEN


async def test_squeeze_in_bypasses_schedule_but_not_overlap(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    doctor, actor = await clinic.add_doctor(), await clinic.staff()
    p1, p2 = await clinic.add_patient("A One"), await clinic.add_patient("B Two", "+919800000002")

    outside = await _book(sessionmaker, actor, p1, doctor, 8, 30)
    assert outside.code is BookingErrorCode.OUTSIDE_SCHEDULE

    squeezed = await _book(sessionmaker, actor, p1, doctor, 8, 30, squeeze_in=True, notes="VIP")
    assert squeezed.ok, squeezed.message
    assert squeezed.unwrap().notes == f"{SQUEEZE_IN_NOTE} VIP"
    [event] = await _events(sessionmaker, squeezed.unwrap().id)
    assert event.note == SQUEEZE_IN_NOTE

    # 08:40 overlaps the squeezed-in 08:30-08:45 appointment: squeeze-in never double-books.
    overlap = await _book(sessionmaker, actor, p2, doctor, 8, 40, squeeze_in=True)
    assert overlap.code is BookingErrorCode.SLOT_TAKEN


async def test_off_grid_time_is_outside_schedule(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    doctor, patient, actor = (
        await clinic.add_doctor(),
        await clinic.add_patient(),
        await clinic.staff(),
    )
    result = await _book(sessionmaker, actor, patient, doctor, 9, 7)
    assert result.code is BookingErrorCode.OUTSIDE_SCHEDULE


async def test_leave_blocks_even_squeeze_in(sessionmaker: Sessions, clinic: ClinicFixture) -> None:
    doctor, patient, actor = (
        await clinic.add_doctor(),
        await clinic.add_patient(),
        await clinic.staff(),
    )
    await clinic.add_leave(doctor, DAY)
    for squeeze_in in (False, True):
        result = await _book(sessionmaker, actor, patient, doctor, 9, squeeze_in=squeeze_in)
        assert result.code is BookingErrorCode.DOCTOR_ON_LEAVE


async def test_past_time_is_rejected(sessionmaker: Sessions, clinic: ClinicFixture) -> None:
    doctor, patient, actor = (
        await clinic.add_doctor(),
        await clinic.add_patient(),
        await clinic.staff(),
    )
    async with sessionmaker() as session:
        result = await create_appointment(
            session, NewAppointment(patient, doctor, ist(9), PHONE), actor, now=ist(9, 30)
        )
    assert result.code is BookingErrorCode.IN_PAST


async def test_permissions(sessionmaker: Sessions, clinic: ClinicFixture) -> None:
    doctor, patient = await clinic.add_doctor(), await clinic.add_patient()
    doctor_actor = await clinic.staff(UserRole.DOCTOR)
    assert (await _book(sessionmaker, doctor_actor, patient, doctor, 9)).code is (
        BookingErrorCode.FORBIDDEN
    )
    bot_squeeze = await _book(
        sessionmaker,
        clinic.system(),
        patient,
        doctor,
        9,
        source=AppointmentSource.WHATSAPP,
        squeeze_in=True,
    )
    assert bot_squeeze.code is BookingErrorCode.FORBIDDEN
    admin = await clinic.staff(UserRole.ADMIN)
    assert (await _book(sessionmaker, admin, patient, doctor, 9)).ok


async def test_cross_clinic_ids_are_not_found(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    doctor, patient, actor = (
        await clinic.add_doctor(),
        await clinic.add_patient(),
        await clinic.staff(),
    )
    assert (await _book(sessionmaker, actor, uuid.uuid4(), doctor, 9)).code is (
        BookingErrorCode.NOT_FOUND
    )
    assert (await _book(sessionmaker, actor, patient, uuid.uuid4(), 9)).code is (
        BookingErrorCode.NOT_FOUND
    )
    other_clinic_actor = StaffActor(actor.user_id, actor.role, uuid.uuid4())
    assert (await _book(sessionmaker, other_clinic_actor, patient, doctor, 9)).code is (
        BookingErrorCode.NOT_FOUND
    )


async def test_tokens_are_never_reused_after_cancellation(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    doctor, actor = await clinic.add_doctor(), await clinic.staff()
    p1, p2 = await clinic.add_patient("A One"), await clinic.add_patient("B Two", "+919800000002")
    first = (await _book(sessionmaker, actor, p1, doctor, 9)).unwrap()
    async with sessionmaker() as session:
        cancelled = await update_appointment_status(
            session, first.id, AppointmentStatus.CANCELLED, actor
        )
    assert cancelled.ok
    rebooked = await _book(sessionmaker, actor, p2, doctor, 9)
    assert rebooked.ok, rebooked.message
    assert rebooked.unwrap().token_number == 2


async def test_tokens_restart_per_doctor_per_day(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    actor, patient = await clinic.staff(), await clinic.add_patient()
    d1 = await clinic.add_doctor(weekdays=(0, 1))
    d2 = await clinic.add_doctor(weekdays=(0,), name="Dr. Other")
    tokens = [
        (await _book(sessionmaker, actor, patient, d1, 9)).unwrap().token_number,
        (await _book(sessionmaker, actor, patient, d1, 9, 15)).unwrap().token_number,
        (await _book(sessionmaker, actor, patient, d2, 9)).unwrap().token_number,
        (await _book(sessionmaker, actor, patient, d1, 9, day=NEXT_DAY)).unwrap().token_number,
    ]
    assert tokens == [1, 2, 1, 1]


async def test_appointment_date_is_clinic_local(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    # 00:30 IST on Tuesday is still Monday in UTC; the booking belongs to Tuesday.
    doctor = await clinic.add_doctor(windows=((time(0), time(1)),), weekdays=(1,))
    actor, patient = await clinic.staff(), await clinic.add_patient()
    result = await _book(sessionmaker, actor, patient, doctor, 0, 30, day=NEXT_DAY)
    assert result.ok, result.message
    assert result.unwrap().appointment_date == NEXT_DAY


async def test_concurrent_bookings_for_same_slot_exactly_one_wins(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    doctor, actor = await clinic.add_doctor(), await clinic.staff()
    patients = [await clinic.add_patient(f"Patient {i}", f"+91980000001{i}") for i in range(5)]
    # Each call opens its own session, i.e. its own database connection.
    results = await asyncio.gather(*(_book(sessionmaker, actor, p, doctor, 9) for p in patients))
    winners = [r for r in results if r.ok]
    assert len(winners) == 1
    assert all(r.code is BookingErrorCode.SLOT_TAKEN for r in results if not r.ok)

    async with sessionmaker() as session:
        count = await session.scalar(
            select(func.count()).select_from(Appointment).where(Appointment.doctor_id == doctor)
        )
    assert count == 1


async def test_concurrent_bookings_get_unique_sequential_tokens(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    doctor = await clinic.add_doctor(windows=((time(9), time(11)),))
    actor, patient = await clinic.staff(), await clinic.add_patient()
    slots = [(9, 0), (9, 15), (9, 30), (9, 45), (10, 0), (10, 15)]
    results = await asyncio.gather(
        *(_book(sessionmaker, actor, patient, doctor, h, m) for h, m in slots)
    )
    assert all(r.ok for r in results), [r.message for r in results]
    assert sorted(r.unwrap().token_number for r in results) == [1, 2, 3, 4, 5, 6]
