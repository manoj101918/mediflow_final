"""Patient medical profile (blood group, allergies, chronic conditions). Doctors only."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PatientMedicalProfile, RecordSourceType
from app.services.booking.actor import StaffActor
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success
from app.services.ingestion.jobs import enqueue
from app.services.records.access import chart_patient

BLOOD_GROUPS = frozenset({"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"})
MAX_ENTRIES = 50
MAX_ENTRY_LENGTH = 100


def clean_entries(values: list[str]) -> list[str]:
    """Trimmed, de-duplicated (case-insensitively), order kept."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in values:
        value = " ".join(raw.split())
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            cleaned.append(value)
    return cleaned


async def get_profile(
    session: AsyncSession, clinic_id: UUID, patient_id: UUID
) -> PatientMedicalProfile | None:
    return await session.scalar(
        select(PatientMedicalProfile).where(
            PatientMedicalProfile.patient_id == patient_id,
            PatientMedicalProfile.clinic_id == clinic_id,
        )
    )


async def update_profile(
    session: AsyncSession,
    actor: StaffActor,
    patient_id: UUID,
    *,
    blood_group: str | None,
    allergies: list[str],
    chronic_conditions: list[str],
) -> BookingResult[PatientMedicalProfile]:
    allowed = await chart_patient(session, actor, patient_id)
    if not allowed.ok:
        return failure(allowed.code or BookingErrorCode.FORBIDDEN, allowed.message)
    if blood_group is not None and blood_group not in BLOOD_GROUPS:
        return failure(BookingErrorCode.VALIDATION, "Choose a valid blood group.")
    allergy_list = clean_entries(allergies)
    condition_list = clean_entries(chronic_conditions)
    for entries in (allergy_list, condition_list):
        if len(entries) > MAX_ENTRIES or any(len(e) > MAX_ENTRY_LENGTH for e in entries):
            return failure(
                BookingErrorCode.VALIDATION,
                f"Up to {MAX_ENTRIES} entries of at most {MAX_ENTRY_LENGTH} characters each.",
            )

    profile = await get_profile(session, actor.clinic_id, patient_id)
    if profile is None:
        profile = PatientMedicalProfile(patient_id=patient_id, clinic_id=actor.clinic_id)
        session.add(profile)
    profile.blood_group = blood_group
    profile.allergies = allergy_list
    profile.chronic_conditions = condition_list
    profile.updated_by = actor.user_id
    await session.flush()
    await enqueue(session, actor.clinic_id, patient_id, RecordSourceType.PROFILE, patient_id)
    await session.commit()
    return success(profile)
