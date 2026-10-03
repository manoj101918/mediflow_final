"""Create and reschedule appointments.

Each call is one transaction: validate, lock the doctor's day, assign the token, write the
appointment and its audit event, then commit. On any failure the session is rolled back
(including pending work the caller added, e.g. a patient from find_or_create_patient).
The database's no-overlap exclusion constraint is the final word on double booking.
Sessions must use expire_on_commit=False so returned objects stay readable.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appointment,
    AppointmentEvent,
    AppointmentSource,
    AppointmentStatus,
    Doctor,
    Patient,
)
from app.services.booking import rules
from app.services.booking.actor import Actor, StaffActor, SystemActor
from app.services.booking.dberrors import booking_error_for
from app.services.booking.ownership import lock_owned_appointment
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success
from app.services.booking.timeutil import local_date, utcnow
from app.services.booking.tokens import lock_doctor_day, next_token

STAFF_SOURCES = frozenset(
    {AppointmentSource.WALK_IN, AppointmentSource.PHONE, AppointmentSource.MANUAL}
)
RESCHEDULABLE = frozenset({AppointmentStatus.PENDING_CONFIRMATION, AppointmentStatus.SCHEDULED})
SQUEEZE_IN_NOTE = "Squeezed in outside the regular schedule."

_SLOT_TAKEN_MESSAGE = "That time was just booked for this doctor. Pick another slot."


@dataclass(frozen=True)
class NewAppointment:
    patient_id: UUID
    doctor_id: UUID
    starts_at: datetime
    source: AppointmentSource
    reason_for_visit: str | None = None
    notes: str | None = None
    # Front desk only: bypass the schedule/slot grid (never the double-booking constraint).
    squeeze_in: bool = False
    # Idempotency key from an external channel (e.g. WhatsApp message id).
    external_ref: str | None = None


@dataclass(frozen=True)
class _PlannedSlot:
    day: date
    starts_at: datetime
    ends_at: datetime
    tz: ZoneInfo

    def local(self, moment: datetime) -> str:
        return moment.astimezone(self.tz).strftime("%d %b %Y %I:%M %p")


async def _plan_slot(
    session: AsyncSession,
    clinic_id: UUID,
    doctor: Doctor,
    starts_at: datetime,
    *,
    squeeze_in: bool,
    now: datetime,
) -> BookingResult[_PlannedSlot]:
    if starts_at.tzinfo is None:
        return failure(BookingErrorCode.VALIDATION, "Appointment time must include a timezone.")
    if starts_at < now - rules.PAST_GRACE:
        return failure(BookingErrorCode.IN_PAST, "That time has already passed.")

    tz = await rules.clinic_timezone(session, clinic_id)
    day = local_date(starts_at, tz)
    if await rules.is_on_leave(session, doctor.id, day):
        return failure(
            BookingErrorCode.DOCTOR_ON_LEAVE, f"{doctor.full_name} is on leave that day."
        )

    if not squeeze_in:
        windows = await rules.schedule_windows(session, doctor.id, day)
        grid = rules.slot_grid(day, windows, doctor.default_slot_minutes, tz)
        if not any(start == starts_at for start, _ in grid):
            return failure(
                BookingErrorCode.OUTSIDE_SCHEDULE,
                f"{doctor.full_name} has no slot at that time. Pick a listed slot or squeeze in.",
            )

    ends_at = starts_at + timedelta(minutes=doctor.default_slot_minutes)
    return success(_PlannedSlot(day=day, starts_at=starts_at, ends_at=ends_at, tz=tz))


def _source_error(source: AppointmentSource, actor: Actor) -> str | None:
    if isinstance(actor, SystemActor):
        if source.value != actor.channel:
            return f"A {actor.channel} booking must use source '{actor.channel}'."
    elif source not in STAFF_SOURCES:
        return "Staff bookings must be walk-in, phone or manual."
    return None


async def _run(
    session: AsyncSession, work: Callable[[], Awaitable[BookingResult[Appointment]]]
) -> BookingResult[Appointment]:
    """Commit on success, roll back on failure; map constraint violations to error codes."""
    try:
        result = await work()
    except DBAPIError as exc:
        await session.rollback()
        code = booking_error_for(exc)
        if code is None:
            raise
        message = (
            "This booking was already received."
            if code is BookingErrorCode.ALREADY_EXISTS
            else _SLOT_TAKEN_MESSAGE
        )
        return failure(code, message)
    if result.ok:
        await session.commit()
    else:
        await session.rollback()
    return result


def _event(
    appointment: Appointment,
    actor: Actor,
    from_status: AppointmentStatus | None,
    note: str | None,
) -> AppointmentEvent:
    return AppointmentEvent(
        clinic_id=appointment.clinic_id,
        appointment_id=appointment.id,
        from_status=from_status,
        to_status=appointment.status,
        changed_by=actor.changed_by,
        actor_type=actor.actor_type,
        channel=actor.channel,
        note=note,
    )


async def create_appointment(
    session: AsyncSession,
    data: NewAppointment,
    actor: Actor,
    *,
    now: datetime | None = None,
) -> BookingResult[Appointment]:
    """Book an appointment. Bot channels create `pending_confirmation`; staff create `scheduled`."""

    async def work() -> BookingResult[Appointment]:
        if isinstance(actor, StaffActor) and not actor.is_front_desk:
            return failure(BookingErrorCode.FORBIDDEN, "Only the front desk can book appointments.")
        if data.squeeze_in and not (isinstance(actor, StaffActor) and actor.is_front_desk):
            return failure(BookingErrorCode.FORBIDDEN, "Only the front desk can squeeze in.")
        if (error := _source_error(data.source, actor)) is not None:
            return failure(BookingErrorCode.VALIDATION, error)

        clinic_id = actor.clinic_id
        patient_ok = await session.scalar(
            select(Patient.id).where(Patient.id == data.patient_id, Patient.clinic_id == clinic_id)
        )
        if patient_ok is None:
            return failure(BookingErrorCode.NOT_FOUND, "Patient not found.")
        doctor = await rules.active_doctor(session, clinic_id, data.doctor_id)
        if doctor is None:
            return failure(BookingErrorCode.NOT_FOUND, "Doctor not found.")

        planned = await _plan_slot(
            session,
            clinic_id,
            doctor,
            data.starts_at,
            squeeze_in=data.squeeze_in,
            now=now or utcnow(),
        )
        if not planned.ok:
            return failure(planned.code or BookingErrorCode.VALIDATION, planned.message)
        slot = planned.unwrap()

        await lock_doctor_day(session, doctor.id, slot.day)
        notes = data.notes
        if data.squeeze_in:
            notes = f"{SQUEEZE_IN_NOTE} {notes}" if notes else SQUEEZE_IN_NOTE
        appointment = Appointment(
            clinic_id=clinic_id,
            patient_id=data.patient_id,
            doctor_id=doctor.id,
            starts_at=slot.starts_at,
            ends_at=slot.ends_at,
            status=(
                AppointmentStatus.PENDING_CONFIRMATION
                if isinstance(actor, SystemActor)
                else AppointmentStatus.SCHEDULED
            ),
            source=data.source,
            token_number=await next_token(session, doctor.id, slot.day),
            reason_for_visit=data.reason_for_visit,
            notes=notes,
            created_by=actor.changed_by,
            external_ref=data.external_ref,
        )
        session.add(appointment)
        await session.flush()
        session.add(_event(appointment, actor, None, SQUEEZE_IN_NOTE if data.squeeze_in else None))
        await session.flush()
        return success(appointment)

    return await _run(session, work)


async def reschedule_appointment(
    session: AsyncSession,
    appointment_id: UUID,
    starts_at: datetime,
    actor: Actor,
    *,
    squeeze_in: bool = False,
    now: datetime | None = None,
) -> BookingResult[Appointment]:
    """Move an upcoming appointment to a new time with the same doctor.

    Moving to another day assigns a fresh token for that day. A bot may move its sender's
    own upcoming appointments (never squeezed in); the move goes back to
    `pending_confirmation` for the front desk to approve again.
    """
    moment = now or utcnow()

    async def load() -> BookingResult[Appointment]:
        if isinstance(actor, SystemActor):
            if squeeze_in:
                return failure(BookingErrorCode.FORBIDDEN, "Only the front desk can squeeze in.")
            return await lock_owned_appointment(session, appointment_id, actor, moment)
        if not actor.is_front_desk:
            return failure(BookingErrorCode.FORBIDDEN, "Only the front desk can reschedule.")
        appointment = await session.scalar(
            select(Appointment)
            .where(Appointment.id == appointment_id, Appointment.clinic_id == actor.clinic_id)
            .with_for_update()
        )
        if appointment is None:
            return failure(BookingErrorCode.NOT_FOUND, "Appointment not found.")
        return success(appointment)

    async def work() -> BookingResult[Appointment]:
        loaded = await load()
        if not loaded.ok:
            return loaded
        appointment = loaded.unwrap()
        if appointment.status not in RESCHEDULABLE:
            return failure(
                BookingErrorCode.INVALID_TRANSITION,
                f"A {appointment.status.value.replace('_', ' ')} appointment cannot be moved.",
            )
        doctor = await rules.active_doctor(session, actor.clinic_id, appointment.doctor_id)
        if doctor is None:
            return failure(BookingErrorCode.NOT_FOUND, "Doctor not found.")

        planned = await _plan_slot(
            session, actor.clinic_id, doctor, starts_at, squeeze_in=squeeze_in, now=moment
        )
        if not planned.ok:
            return failure(planned.code or BookingErrorCode.VALIDATION, planned.message)
        slot = planned.unwrap()
        if slot.starts_at == appointment.starts_at:
            return failure(BookingErrorCode.VALIDATION, "The appointment is already at that time.")

        await lock_doctor_day(session, doctor.id, slot.day)
        if slot.day != appointment.appointment_date:
            appointment.token_number = await next_token(session, doctor.id, slot.day)
        previous = appointment.starts_at
        previous_status = appointment.status
        appointment.starts_at = slot.starts_at
        appointment.ends_at = slot.ends_at
        if isinstance(actor, SystemActor):
            appointment.status = AppointmentStatus.PENDING_CONFIRMATION
        await session.flush()
        note = f"Rescheduled from {slot.local(previous)} to {slot.local(slot.starts_at)}."
        if squeeze_in:
            note = f"{note} {SQUEEZE_IN_NOTE}"
        session.add(_event(appointment, actor, previous_status, note))
        await session.flush()
        return success(appointment)

    return await _run(session, work)
