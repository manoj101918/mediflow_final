"""Consultations (one per appointment), their prescriptions and addenda.

Rules:
- Only the appointment's own doctor writes its consultation, and only while the appointment is
  checked_in or in_consultation. Other doctors get NOT_FOUND (as in the booking service);
  reception/admin get FORBIDDEN.
- Completing the appointment finalizes the draft in the same transaction. A finalized
  consultation is read-only (RECORD_LOCKED); corrections are addenda.
- Every change that the chatbot should know about enqueues an ingestion job in the same
  transaction.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appointment,
    AppointmentStatus,
    Consultation,
    ConsultationAddendum,
    ConsultationStatus,
    Prescription,
    PrescriptionItem,
    Profile,
    RecordSourceType,
)
from app.services.booking.actor import StaffActor
from app.services.booking.dberrors import booking_error_for
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success
from app.services.booking.status import transition_in_session
from app.services.ingestion.jobs import enqueue
from app.services.records.access import clinician_check

EDITABLE_STATUSES = frozenset({AppointmentStatus.CHECKED_IN, AppointmentStatus.IN_CONSULTATION})

CONSULTATION_FIELDS = frozenset(
    {
        "chief_complaint",
        "history",
        "examination",
        "diagnosis",
        "advice",
        "follow_up_date",
        "notes",
        "vitals",
    }
)

LOCKED_MESSAGE = "This visit has been finalized. Add an addendum instead."


@dataclass(frozen=True)
class ItemInput:
    medicine_name: str
    strength: str | None = None
    dosage_form: str | None = None
    dose: str | None = None
    route: str | None = None
    frequency: str | None = None
    timing: str | None = None
    duration_days: int | None = None
    instructions: str | None = None


@dataclass(frozen=True)
class ConsultationInput:
    # Only the keys present are changed (subset of CONSULTATION_FIELDS).
    fields: dict[str, Any] = field(default_factory=dict)
    # None leaves the prescription unchanged; a list replaces all items (in this order).
    items: list[ItemInput] | None = None


@dataclass(frozen=True)
class Visit:
    appointment: Appointment
    consultation: Consultation | None
    items: list[PrescriptionItem]


async def _items(session: AsyncSession, consultation_id: UUID) -> list[PrescriptionItem]:
    rows = await session.scalars(
        select(PrescriptionItem)
        .join(Prescription, Prescription.id == PrescriptionItem.prescription_id)
        .where(Prescription.consultation_id == consultation_id)
        .order_by(PrescriptionItem.sort_order, PrescriptionItem.created_at)
    )
    return list(rows)


async def get_visit(
    session: AsyncSession, actor: StaffActor, appointment_id: UUID
) -> BookingResult[Visit]:
    """An appointment's consultation (if any), readable by any doctor of the clinic."""
    check = clinician_check(actor)
    if not check.ok:
        return failure(check.code or BookingErrorCode.FORBIDDEN, check.message)
    appointment = await session.scalar(
        select(Appointment).where(
            Appointment.id == appointment_id, Appointment.clinic_id == actor.clinic_id
        )
    )
    if appointment is None:
        return failure(BookingErrorCode.NOT_FOUND, "Appointment not found.")
    consultation = await session.scalar(
        select(Consultation).where(Consultation.appointment_id == appointment_id)
    )
    items = await _items(session, consultation.id) if consultation else []
    return success(Visit(appointment, consultation, items))


async def _own_appointment(
    session: AsyncSession, actor: StaffActor, appointment_id: UUID
) -> BookingResult[Appointment]:
    check = clinician_check(actor)
    if not check.ok:
        return failure(check.code or BookingErrorCode.FORBIDDEN, check.message)
    appointment = await session.scalar(
        select(Appointment)
        .where(Appointment.id == appointment_id, Appointment.clinic_id == actor.clinic_id)
        .with_for_update()
    )
    # Another doctor's appointment is reported as missing, like the booking service does.
    if appointment is None or appointment.doctor_id != actor.doctor_id:
        return failure(BookingErrorCode.NOT_FOUND, "Appointment not found.")
    return success(appointment)


async def save_draft(
    session: AsyncSession, actor: StaffActor, appointment_id: UUID, data: ConsultationInput
) -> BookingResult[Visit]:
    """Create or update the draft consultation (and prescription) for the doctor's own visit."""
    try:
        result = await _save_draft(session, actor, appointment_id, data)
    except DBAPIError as exc:
        await session.rollback()
        code = booking_error_for(exc)
        if code is None:
            raise
        return failure(code, LOCKED_MESSAGE if code is BookingErrorCode.RECORD_LOCKED else "")
    if result.ok:
        await session.commit()
    else:
        await session.rollback()
    return result


async def _save_draft(
    session: AsyncSession, actor: StaffActor, appointment_id: UUID, data: ConsultationInput
) -> BookingResult[Visit]:
    owned = await _own_appointment(session, actor, appointment_id)
    if not owned.ok:
        return failure(owned.code or BookingErrorCode.NOT_FOUND, owned.message)
    appointment = owned.unwrap()

    consultation = await session.scalar(
        select(Consultation).where(Consultation.appointment_id == appointment_id).with_for_update()
    )
    if consultation is not None and consultation.status is ConsultationStatus.FINALIZED:
        return failure(BookingErrorCode.RECORD_LOCKED, LOCKED_MESSAGE)
    if appointment.status not in EDITABLE_STATUSES:
        return failure(
            BookingErrorCode.INVALID_TRANSITION,
            "Notes can only be written while the patient is checked in or in consultation.",
        )
    unknown = set(data.fields) - CONSULTATION_FIELDS
    if unknown:
        return failure(BookingErrorCode.VALIDATION, f"Unknown fields: {', '.join(sorted(unknown))}")

    if consultation is None:
        consultation = Consultation(
            clinic_id=appointment.clinic_id,
            appointment_id=appointment.id,
            patient_id=appointment.patient_id,
            doctor_id=appointment.doctor_id,
            created_by=actor.user_id,
        )
        session.add(consultation)
    for name, value in data.fields.items():
        setattr(consultation, name, value)
    await session.flush()

    if data.items is not None:
        await _replace_items(session, consultation, data.items)
    return success(Visit(appointment, consultation, await _items(session, consultation.id)))


async def _replace_items(
    session: AsyncSession, consultation: Consultation, items: list[ItemInput]
) -> None:
    prescription = await session.scalar(
        select(Prescription).where(Prescription.consultation_id == consultation.id)
    )
    if prescription is None:
        if not items:
            return
        prescription = Prescription(
            clinic_id=consultation.clinic_id,
            consultation_id=consultation.id,
            patient_id=consultation.patient_id,
        )
        session.add(prescription)
        await session.flush()
    await session.execute(
        delete(PrescriptionItem).where(PrescriptionItem.prescription_id == prescription.id)
    )
    for index, item in enumerate(items):
        session.add(
            PrescriptionItem(
                prescription_id=prescription.id,
                sort_order=index,
                medicine_name=item.medicine_name,
                strength=item.strength,
                dosage_form=item.dosage_form,
                dose=item.dose,
                route=item.route,
                frequency=item.frequency,
                timing=item.timing,
                duration_days=item.duration_days,
                instructions=item.instructions,
            )
        )
    await session.flush()


@dataclass(frozen=True)
class CompletedVisit:
    appointment: Appointment
    consultation: Consultation | None


async def complete_visit(
    session: AsyncSession, actor: StaffActor, appointment_id: UUID, note: str | None = None
) -> BookingResult[CompletedVisit]:
    """Complete the appointment and finalize its draft consultation in ONE transaction.

    Used by every path that completes an appointment (doctor's Complete button and the generic
    status endpoint), so a draft is never left behind on a completed visit. Completing with no
    consultation is allowed.
    """
    try:
        result = await _complete(session, actor, appointment_id, note)
    except DBAPIError as exc:
        await session.rollback()
        code = booking_error_for(exc)
        if code is None:
            raise
        return failure(code, LOCKED_MESSAGE if code is BookingErrorCode.RECORD_LOCKED else "")
    if result.ok:
        await session.commit()
    else:
        await session.rollback()
    return result


async def _complete(
    session: AsyncSession, actor: StaffActor, appointment_id: UUID, note: str | None
) -> BookingResult[CompletedVisit]:
    moved = await transition_in_session(
        session, appointment_id, AppointmentStatus.COMPLETED, actor, note=note
    )
    if not moved.ok:
        return failure(moved.code or BookingErrorCode.INVALID_TRANSITION, moved.message)
    appointment = moved.unwrap()

    consultation = await session.scalar(
        select(Consultation).where(Consultation.appointment_id == appointment_id).with_for_update()
    )
    if consultation is not None and consultation.status is ConsultationStatus.DRAFT:
        consultation.status = ConsultationStatus.FINALIZED
        consultation.finalized_at = datetime.now(UTC)
        await session.flush()
        await enqueue(
            session,
            consultation.clinic_id,
            consultation.patient_id,
            RecordSourceType.CONSULTATION,
            consultation.id,
        )
    return success(CompletedVisit(appointment, consultation))


async def add_addendum(
    session: AsyncSession, actor: StaffActor, consultation_id: UUID, body: str
) -> BookingResult[ConsultationAddendum]:
    """Append a correction to a finalized consultation (any doctor of the clinic)."""
    check = clinician_check(actor)
    if not check.ok:
        return failure(check.code or BookingErrorCode.FORBIDDEN, check.message)
    text_value = body.strip()
    if not text_value:
        return failure(BookingErrorCode.VALIDATION, "Write the addendum text.")
    consultation = await session.scalar(
        select(Consultation).where(
            Consultation.id == consultation_id, Consultation.clinic_id == actor.clinic_id
        )
    )
    if consultation is None:
        return failure(BookingErrorCode.NOT_FOUND, "Visit not found.")
    if consultation.status is not ConsultationStatus.FINALIZED:
        return failure(
            BookingErrorCode.INVALID_TRANSITION,
            "This visit is still a draft; edit it directly instead of adding an addendum.",
        )
    author_name = await session.scalar(select(Profile.full_name).where(Profile.id == actor.user_id))
    addendum = ConsultationAddendum(
        clinic_id=consultation.clinic_id,
        consultation_id=consultation.id,
        author_id=actor.user_id,
        author_name=author_name or "Unknown",
        text=text_value,
    )
    session.add(addendum)
    await session.flush()
    await enqueue(
        session,
        consultation.clinic_id,
        consultation.patient_id,
        RecordSourceType.CONSULTATION,
        consultation.id,
    )
    await session.commit()
    return success(addendum)
