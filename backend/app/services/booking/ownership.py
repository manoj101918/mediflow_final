"""What a bot may change: upcoming appointments of patients registered with the sender's phone.

Bots never see other people's appointments, so anything else is reported as missing.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment, AppointmentStatus, Patient
from app.services.booking.actor import SystemActor
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success

BOT_CHANGEABLE = frozenset({AppointmentStatus.PENDING_CONFIRMATION, AppointmentStatus.SCHEDULED})


async def lock_owned_appointment(
    session: AsyncSession, appointment_id: UUID, actor: SystemActor, now: datetime
) -> BookingResult[Appointment]:
    """Lock an upcoming appointment that belongs to the actor's phone."""
    if actor.phone_e164 is None:
        return failure(
            BookingErrorCode.FORBIDDEN, "Automated channels can only change their own bookings."
        )
    appointment = await session.scalar(
        select(Appointment)
        .join(Patient, Patient.id == Appointment.patient_id)
        .where(
            Appointment.id == appointment_id,
            Appointment.clinic_id == actor.clinic_id,
            Patient.phone == actor.phone_e164,
        )
        .with_for_update(of=Appointment)
    )
    if appointment is None:
        return failure(BookingErrorCode.NOT_FOUND, "Appointment not found.")
    if appointment.status not in BOT_CHANGEABLE or appointment.starts_at <= now:
        return failure(
            BookingErrorCode.INVALID_TRANSITION, "Only upcoming appointments can be changed."
        )
    return success(appointment)
