"""Patient lookup shared by every booking channel.

Families often share one phone number, so a phone match alone is not the same patient: the name
must also be similar (pg_trgm similarity above DUPLICATE_NAME_SIMILARITY).
"""

from dataclasses import dataclass
from uuid import UUID

import phonenumbers
from sqlalchemy import ColumnElement, Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute

from app.db.models import Gender, Patient
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success

DEFAULT_PHONE_REGION = "IN"
DUPLICATE_NAME_SIMILARITY = 0.6


def normalize_phone(raw: str, region: str = DEFAULT_PHONE_REGION) -> str | None:
    """E.164 (+919848012345) for a valid number; 10-digit numbers default to India. Else None."""
    try:
        parsed = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def name_similarity(column: QueryableAttribute[str], name: str) -> ColumnElement[float]:
    """pg_trgm similarity (0..1) between a name column and a name, case-insensitive."""
    return func.extensions.similarity(func.lower(column), func.lower(name), type_=Float)


@dataclass(frozen=True)
class PatientMatch:
    patient: Patient
    created: bool


async def find_or_create_patient(
    session: AsyncSession,
    clinic_id: UUID,
    phone: str,
    full_name: str,
    *,
    created_by: UUID | None = None,
    gender: Gender | None = None,
    age_years: int | None = None,
) -> BookingResult[PatientMatch]:
    """Reuse the clinic patient with this phone and a similar name, or create one.

    Adds to the session and flushes but does not commit; the caller owns the transaction.
    """
    name = " ".join(full_name.split())
    if not name:
        return failure(BookingErrorCode.VALIDATION, "Patient name is required.")
    normalized = normalize_phone(phone)
    if normalized is None:
        return failure(BookingErrorCode.VALIDATION, "Enter a valid phone number.")

    similarity = name_similarity(Patient.full_name, name)
    existing = await session.scalar(
        select(Patient)
        .where(
            Patient.clinic_id == clinic_id,
            Patient.phone == normalized,
            similarity > DUPLICATE_NAME_SIMILARITY,
        )
        .order_by(similarity.desc())
        .limit(1)
    )
    if existing is not None:
        return success(PatientMatch(existing, created=False))

    patient = Patient(
        clinic_id=clinic_id,
        full_name=name,
        phone=normalized,
        gender=gender,
        age_years=age_years,
        created_by=created_by,
    )
    session.add(patient)
    await session.flush()
    return success(PatientMatch(patient, created=True))
