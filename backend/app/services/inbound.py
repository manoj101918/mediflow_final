"""Bookings from automated channels (WhatsApp / voice bots).

Every request is stored before anything else, keyed by (clinic, channel, external_ref), so a
bot that retries never books twice. Bookings go through the same booking service as the
front desk, as a SystemActor: they arrive as `pending_confirmation` for the front desk to
approve. Anything that cannot be booked automatically is kept as `needs_review`.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appointment,
    AppointmentSource,
    Doctor,
    InboundBookingRequest,
    InboundChannel,
    InboundStatus,
)
from app.services.booking import (
    BookingErrorCode,
    NewAppointment,
    Slot,
    SystemActor,
    create_appointment,
    find_or_create_patient,
    get_available_slots,
    normalize_phone,
    rules,
)
from app.services.booking.actor import SystemChannel
from app.services.booking.timeutil import local_date, today_local, utcnow

SUGGESTION_COUNT = 5
SUGGESTION_DAYS = 3


@dataclass(frozen=True)
class InboundBooking:
    channel: InboundChannel
    external_ref: str
    caller_phone: str
    patient_name: str
    doctor_id: UUID | None
    requested_time: datetime | None
    reason: str | None


@dataclass(frozen=True)
class InboundOutcome:
    request: InboundBookingRequest
    duplicate: bool = False
    appointment: Appointment | None = None
    doctor_name: str | None = None
    code: BookingErrorCode | None = None
    message: str = ""
    suggested: list[Slot] = field(default_factory=list)


async def record_request(
    session: AsyncSession,
    clinic_id: UUID,
    channel: InboundChannel,
    external_ref: str,
    raw_payload: dict[str, Any],
) -> tuple[InboundBookingRequest, bool]:
    """Store the raw request (committed) or return the earlier one with this external_ref."""

    async def existing() -> InboundBookingRequest | None:
        return await session.scalar(
            select(InboundBookingRequest).where(
                InboundBookingRequest.clinic_id == clinic_id,
                InboundBookingRequest.channel == channel,
                InboundBookingRequest.external_ref == external_ref,
            )
        )

    if (earlier := await existing()) is not None:
        return earlier, True
    request = InboundBookingRequest(
        clinic_id=clinic_id, channel=channel, external_ref=external_ref, raw_payload=raw_payload
    )
    session.add(request)
    try:
        await session.commit()
    except IntegrityError:
        # The same request arrived twice at once; the other copy won the insert.
        await session.rollback()
        earlier = await existing()
        assert earlier is not None  # noqa: S101 - the unique index guarantees it exists
        return earlier, True
    return request, False


async def describe(session: AsyncSession, request: InboundBookingRequest) -> InboundOutcome:
    """Current state of an earlier request (for duplicates)."""
    appointment, doctor_name = None, None
    if request.appointment_id is not None:
        row = (
            await session.execute(
                select(Appointment, Doctor.full_name)
                .join(Doctor, Doctor.id == Appointment.doctor_id)
                .where(Appointment.id == request.appointment_id)
            )
        ).first()
        if row is not None:
            appointment, doctor_name = row
    return InboundOutcome(
        request=request,
        duplicate=True,
        appointment=appointment,
        doctor_name=doctor_name,
        message="This request was already received.",
    )


async def _finish(
    session: AsyncSession,
    request_id: UUID,
    status: InboundStatus,
    *,
    error: str | None = None,
    appointment_id: UUID | None = None,
) -> InboundBookingRequest:
    await session.execute(
        update(InboundBookingRequest)
        .where(InboundBookingRequest.id == request_id)
        .values(status=status, error=error, appointment_id=appointment_id)
    )
    await session.commit()
    request = await session.get(InboundBookingRequest, request_id, populate_existing=True)
    assert request is not None  # noqa: S101 - stored by record_request
    return request


async def _suggestions(
    session: AsyncSession, clinic_id: UUID, doctor_id: UUID, wanted: datetime | None
) -> list[Slot]:
    """Next free slots from the requested day (or today), looking a few days ahead."""
    tz = await rules.clinic_timezone(session, clinic_id)
    day = max(local_date(wanted, tz), today_local(tz)) if wanted else today_local(tz)
    found: list[Slot] = []
    for offset in range(SUGGESTION_DAYS):
        result = await get_available_slots(session, clinic_id, doctor_id, day + timedelta(offset))
        if result.ok:
            found.extend(result.unwrap().slots)
        if len(found) >= SUGGESTION_COUNT:
            break
    return found[:SUGGESTION_COUNT]


def _system_channel(channel: InboundChannel) -> SystemChannel:
    return "whatsapp" if channel is InboundChannel.WHATSAPP else "voice"


async def process_request(
    session: AsyncSession, clinic_id: UUID, request_id: UUID, data: InboundBooking
) -> InboundOutcome:
    """Try to book a stored request; record the outcome on it."""
    phone = normalize_phone(data.caller_phone)
    doctor = (
        await rules.active_doctor(session, clinic_id, data.doctor_id) if data.doctor_id else None
    )
    # Plain values: a failed booking rolls the session back, which expires loaded objects.
    doctor_id = doctor.id if doctor else None
    doctor_name = doctor.full_name if doctor else None
    await session.execute(
        update(InboundBookingRequest)
        .where(InboundBookingRequest.id == request_id)
        .values(
            caller_phone=phone or data.caller_phone,
            parsed_patient_name=data.patient_name,
            requested_doctor_id=doctor_id,
            requested_time=data.requested_time,
        )
    )
    await session.commit()

    async def review(code: BookingErrorCode, message: str) -> InboundOutcome:
        suggested = (
            await _suggestions(session, clinic_id, doctor_id, data.requested_time)
            if doctor_id is not None
            else []
        )
        request = await _finish(
            session, request_id, InboundStatus.NEEDS_REVIEW, error=f"{code.value}: {message}"
        )
        return InboundOutcome(request=request, code=code, message=message, suggested=suggested)

    if phone is None:
        message = "The caller's phone number is not valid."
        request = await _finish(
            session, request_id, InboundStatus.REJECTED, error=f"VALIDATION: {message}"
        )
        return InboundOutcome(request=request, code=BookingErrorCode.VALIDATION, message=message)
    if data.doctor_id is not None and doctor_id is None:
        return await review(BookingErrorCode.NOT_FOUND, "The requested doctor was not found.")
    if doctor_id is None or data.requested_time is None:
        return await review(
            BookingErrorCode.VALIDATION,
            "No doctor or time was requested; the clinic will call back.",
        )

    patient = await find_or_create_patient(session, clinic_id, phone, data.patient_name)
    if not patient.ok:
        await session.rollback()
        message = patient.message
        request = await _finish(
            session, request_id, InboundStatus.REJECTED, error=f"VALIDATION: {message}"
        )
        return InboundOutcome(request=request, code=BookingErrorCode.VALIDATION, message=message)

    booked = await create_appointment(
        session,
        NewAppointment(
            patient_id=patient.unwrap().patient.id,
            doctor_id=doctor_id,
            starts_at=data.requested_time,
            source=AppointmentSource(data.channel.value),
            reason_for_visit=data.reason,
            external_ref=data.external_ref,
        ),
        SystemActor(channel=_system_channel(data.channel), clinic_id=clinic_id),
        now=utcnow(),
    )
    if not booked.ok:
        return await review(booked.code or BookingErrorCode.VALIDATION, booked.message)

    appointment = booked.unwrap()
    request = await _finish(
        session, request_id, InboundStatus.AUTO_BOOKED, appointment_id=appointment.id
    )
    return InboundOutcome(
        request=request,
        appointment=appointment,
        doctor_name=doctor_name,
        message="Booked. The clinic will confirm shortly.",
    )


async def mark_rejected(
    session: AsyncSession, clinic_id: UUID, request_id: UUID, error: str
) -> InboundBookingRequest | None:
    request = await session.scalar(
        select(InboundBookingRequest).where(
            InboundBookingRequest.id == request_id, InboundBookingRequest.clinic_id == clinic_id
        )
    )
    if request is None:
        return None
    return await _finish(session, request_id, InboundStatus.REJECTED, error=error)


async def list_requests(
    session: AsyncSession, clinic_id: UUID, status: InboundStatus | None, since: datetime
) -> list[tuple[InboundBookingRequest, str | None]]:
    stmt = (
        select(InboundBookingRequest, Doctor.full_name)
        .outerjoin(Doctor, Doctor.id == InboundBookingRequest.requested_doctor_id)
        .where(
            InboundBookingRequest.clinic_id == clinic_id,
            InboundBookingRequest.created_at >= since,
        )
        .order_by(InboundBookingRequest.created_at.desc())
        .limit(100)
    )
    if status is not None:
        stmt = stmt.where(InboundBookingRequest.status == status)
    return [(request, name) for request, name in await session.execute(stmt)]
