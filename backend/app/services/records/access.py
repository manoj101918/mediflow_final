"""Who may read or write a patient's clinical record.

- Any active doctor (login linked to a doctor profile) may read the full chart of any patient
  in their clinic: every visit, prescription, addendum and report, whoever wrote it.
- Reception and admin never read clinical content (FORBIDDEN). They may upload reports and
  see report metadata (title, type, date, status).
- Writing a consultation is limited to the doctor's own appointment (see consultations.py).
- Patients outside the actor's clinic do not exist for them (NOT_FOUND).
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Patient, UserRole
from app.services.booking.actor import StaffActor
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success

NOT_CLINICIAN = "Only doctors can view clinical records."
NOT_LINKED = "Your login is not linked to a doctor."


def is_clinician(actor: StaffActor) -> bool:
    return actor.role == UserRole.DOCTOR and actor.doctor_id is not None


def clinician_check(actor: StaffActor) -> BookingResult[UUID]:
    """The actor's doctor id if they may read clinical records."""
    if actor.role != UserRole.DOCTOR:
        return failure(BookingErrorCode.FORBIDDEN, NOT_CLINICIAN)
    if actor.doctor_id is None:
        return failure(BookingErrorCode.FORBIDDEN, NOT_LINKED)
    return success(actor.doctor_id)


async def clinic_patient(
    session: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> Patient | None:
    return await session.scalar(
        select(Patient).where(Patient.id == patient_id, Patient.clinic_id == clinic_id)
    )


async def chart_patient(
    session: AsyncSession, actor: StaffActor, patient_id: UUID
) -> BookingResult[Patient]:
    """The patient, if the actor may read their clinical record."""
    check = clinician_check(actor)
    if not check.ok:
        return failure(check.code or BookingErrorCode.FORBIDDEN, check.message)
    patient = await clinic_patient(session, actor.clinic_id, patient_id)
    if patient is None:
        return failure(BookingErrorCode.NOT_FOUND, "Patient not found.")
    return success(patient)


async def report_patient(
    session: AsyncSession, actor: StaffActor, patient_id: UUID
) -> BookingResult[Patient]:
    """The patient, if the actor may upload reports or list report metadata for them."""
    if not (actor.is_front_desk or is_clinician(actor)):
        return failure(BookingErrorCode.FORBIDDEN, NOT_LINKED)
    patient = await clinic_patient(session, actor.clinic_id, patient_id)
    if patient is None:
        return failure(BookingErrorCode.NOT_FOUND, "Patient not found.")
    return success(patient)
