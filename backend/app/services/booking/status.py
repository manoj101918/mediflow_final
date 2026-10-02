"""Appointment status transitions (one transaction each, with an audit event)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment, AppointmentEvent, AppointmentStatus
from app.services.booking.actor import Actor, StaffActor
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success

S = AppointmentStatus

ALLOWED_TRANSITIONS: dict[AppointmentStatus, frozenset[AppointmentStatus]] = {
    S.PENDING_CONFIRMATION: frozenset({S.SCHEDULED, S.CANCELLED}),
    S.SCHEDULED: frozenset({S.CHECKED_IN, S.CANCELLED, S.NO_SHOW}),
    S.CHECKED_IN: frozenset({S.IN_CONSULTATION, S.CANCELLED, S.NO_SHOW}),
    S.IN_CONSULTATION: frozenset({S.COMPLETED}),
    S.COMPLETED: frozenset(),
    S.CANCELLED: frozenset(),
    S.NO_SHOW: frozenset(),
}

# Doctors may only start and finish consultations, and only on their own appointments.
DOCTOR_TRANSITIONS = frozenset(
    {(S.CHECKED_IN, S.IN_CONSULTATION), (S.IN_CONSULTATION, S.COMPLETED)}
)


def can_transition(current: AppointmentStatus, target: AppointmentStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def _label(status: AppointmentStatus) -> str:
    return status.value.replace("_", " ")


async def update_appointment_status(
    session: AsyncSession,
    appointment_id: UUID,
    target: AppointmentStatus,
    actor: Actor,
    *,
    note: str | None = None,
    require_current: AppointmentStatus | None = None,
) -> BookingResult[Appointment]:
    """Move an appointment to `target` if the transition and the actor allow it."""
    result = await _transition(session, appointment_id, target, actor, note, require_current)
    if result.ok:
        await session.commit()
    else:
        await session.rollback()
    return result


async def _transition(
    session: AsyncSession,
    appointment_id: UUID,
    target: AppointmentStatus,
    actor: Actor,
    note: str | None,
    require_current: AppointmentStatus | None,
) -> BookingResult[Appointment]:
    if not isinstance(actor, StaffActor):
        return failure(BookingErrorCode.FORBIDDEN, "Automated channels cannot change status.")

    appointment = await session.scalar(
        select(Appointment)
        .where(Appointment.id == appointment_id, Appointment.clinic_id == actor.clinic_id)
        .with_for_update()
    )
    # Doctors cannot see other doctors' appointments at all, so report them as missing.
    if appointment is None or (
        not actor.is_front_desk and appointment.doctor_id != actor.doctor_id
    ):
        return failure(BookingErrorCode.NOT_FOUND, "Appointment not found.")

    current = appointment.status
    if require_current is not None and current is not require_current:
        return failure(
            BookingErrorCode.INVALID_TRANSITION,
            f"Only {_label(require_current)} appointments can do this "
            f"(this one is {_label(current)}).",
        )
    if not can_transition(current, target):
        return failure(
            BookingErrorCode.INVALID_TRANSITION,
            f"Cannot change a {_label(current)} appointment to {_label(target)}.",
        )
    if not actor.is_front_desk and (current, target) not in DOCTOR_TRANSITIONS:
        return failure(
            BookingErrorCode.FORBIDDEN, "Doctors can only start and complete consultations."
        )

    appointment.status = target
    await session.flush()
    session.add(
        AppointmentEvent(
            clinic_id=appointment.clinic_id,
            appointment_id=appointment.id,
            from_status=current,
            to_status=target,
            changed_by=actor.changed_by,
            actor_type=actor.actor_type,
            channel=actor.channel,
            note=note,
        )
    )
    await session.flush()
    return success(appointment)


async def approve_appointment(
    session: AsyncSession, appointment_id: UUID, actor: Actor
) -> BookingResult[Appointment]:
    """Confirm a bot booking that is waiting for the front desk."""
    return await update_appointment_status(
        session,
        appointment_id,
        S.SCHEDULED,
        actor,
        note="Approved by front desk.",
        require_current=S.PENDING_CONFIRMATION,
    )


async def reject_appointment(
    session: AsyncSession, appointment_id: UUID, actor: Actor, reason: str | None = None
) -> BookingResult[Appointment]:
    """Decline a pending bot booking; its slot is released."""
    return await update_appointment_status(
        session,
        appointment_id,
        S.CANCELLED,
        actor,
        note=f"Rejected: {reason}" if reason else "Rejected by front desk.",
        require_current=S.PENDING_CONFIRMATION,
    )
