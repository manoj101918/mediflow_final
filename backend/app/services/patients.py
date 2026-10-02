"""Patient records: search, create, edit, history, duplicate detection."""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import Float, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment, Doctor, Patient
from app.services.booking.patients import (
    DUPLICATE_NAME_SIMILARITY,
    name_similarity,
    normalize_phone,
)
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success

# Search compares the query with the best-matching part of the name (pg_trgm word_similarity),
# so one word or a misspelling still matches ("laxmi" -> "Lakshmi Narayanan").
SEARCH_WORD_SIMILARITY = 0.3
_PHONE_FIELDS = ("phone", "alternate_phone")


def patient_age(patient: Patient, today: date) -> int | None:
    dob = patient.date_of_birth
    if dob is not None:
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return patient.age_years


async def search_patients(
    session: AsyncSession, clinic_id: UUID, query: str | None, page: int, page_size: int
) -> tuple[list[Patient], int]:
    """Name (fuzzy) or phone (digits anywhere in the number) search, paginated."""
    stmt = select(Patient).where(Patient.clinic_id == clinic_id)
    q = (query or "").strip()
    digits = re.sub(r"\D", "", q)
    if q and len(digits) >= 3 and len(digits) >= len(q.replace(" ", "")) - 1:
        stmt = stmt.where(
            or_(Patient.phone.contains(digits), Patient.alternate_phone.contains(digits))
        )
        order: list[Any] = [Patient.full_name]
    elif q:
        word_score = func.extensions.word_similarity(
            func.lower(q), func.lower(Patient.full_name), type_=Float
        )
        stmt = stmt.where(
            or_(
                Patient.full_name.icontains(q, autoescape=True),
                word_score >= SEARCH_WORD_SIMILARITY,
            )
        )
        order = [word_score.desc(), name_similarity(Patient.full_name, q).desc(), Patient.full_name]
    else:
        order = [Patient.created_at.desc()]

    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await session.scalars(
        stmt.order_by(*order).offset((page - 1) * page_size).limit(page_size)
    )
    return list(rows), total


def _normalize_phones(values: dict[str, Any]) -> BookingResult[dict[str, Any]]:
    for field in _PHONE_FIELDS:
        raw = values.get(field)
        if raw is None:
            continue
        normalized = normalize_phone(raw)
        if normalized is None:
            label = "phone" if field == "phone" else "alternate phone"
            return failure(BookingErrorCode.VALIDATION, f"Enter a valid {label} number.")
        values[field] = normalized
    return success(values)


async def create_patient(
    session: AsyncSession, clinic_id: UUID, values: dict[str, Any], created_by: UUID | None
) -> BookingResult[Patient]:
    checked = _normalize_phones(dict(values))
    if not checked.ok:
        return failure(checked.code or BookingErrorCode.VALIDATION, checked.message)
    patient = Patient(clinic_id=clinic_id, created_by=created_by, **checked.unwrap())
    session.add(patient)
    await session.commit()
    return success(patient)


async def update_patient(
    session: AsyncSession, clinic_id: UUID, patient_id: UUID, changes: dict[str, Any]
) -> BookingResult[Patient]:
    if "phone" in changes and changes["phone"] is None:
        return failure(BookingErrorCode.VALIDATION, "Phone number is required.")
    if "full_name" in changes and changes["full_name"] is None:
        return failure(BookingErrorCode.VALIDATION, "Name is required.")
    checked = _normalize_phones(dict(changes))
    if not checked.ok:
        return failure(checked.code or BookingErrorCode.VALIDATION, checked.message)

    patient = await session.scalar(
        select(Patient).where(Patient.id == patient_id, Patient.clinic_id == clinic_id)
    )
    if patient is None:
        return failure(BookingErrorCode.NOT_FOUND, "Patient not found.")
    for field, value in checked.unwrap().items():
        setattr(patient, field, value)
    await session.commit()
    return success(patient)


async def get_patient(session: AsyncSession, clinic_id: UUID, patient_id: UUID) -> Patient | None:
    return await session.scalar(
        select(Patient).where(Patient.id == patient_id, Patient.clinic_id == clinic_id)
    )


async def patient_history(
    session: AsyncSession, patient_id: UUID, limit: int = 100
) -> list[tuple[Appointment, str]]:
    rows = await session.execute(
        select(Appointment, Doctor.full_name)
        .join(Doctor, Doctor.id == Appointment.doctor_id)
        .where(Appointment.patient_id == patient_id)
        .order_by(Appointment.starts_at.desc())
        .limit(limit)
    )
    return [(appointment, doctor_name) for appointment, doctor_name in rows]


DuplicateReason = Literal["same_phone", "similar_name", "same_phone_similar_name"]


@dataclass(frozen=True)
class Duplicate:
    patient: Patient
    reason: DuplicateReason


async def find_duplicates(
    session: AsyncSession,
    clinic_id: UUID,
    *,
    phone: str | None,
    full_name: str | None,
    exclude_id: UUID | None = None,
    limit: int = 10,
) -> list[Duplicate]:
    """Existing patients that look like the one being entered (same phone or similar name)."""
    normalized = normalize_phone(phone) if phone else None
    name = " ".join((full_name or "").split())
    if normalized is None and not name:
        return []

    conditions = []
    if normalized:
        conditions.append(Patient.phone == normalized)
        conditions.append(Patient.alternate_phone == normalized)
    similarity = name_similarity(Patient.full_name, name) if name else literal(0.0, Float)
    if name:
        conditions.append(similarity > DUPLICATE_NAME_SIMILARITY)

    stmt = select(Patient, similarity).where(Patient.clinic_id == clinic_id, or_(*conditions))
    if exclude_id is not None:
        stmt = stmt.where(Patient.id != exclude_id)
    rows = await session.execute(stmt.order_by(similarity.desc(), Patient.full_name).limit(limit))

    duplicates: list[Duplicate] = []
    for patient, score in rows:
        same_phone = normalized is not None and normalized in (
            patient.phone,
            patient.alternate_phone,
        )
        similar = score > DUPLICATE_NAME_SIMILARITY
        reason: DuplicateReason = (
            "same_phone_similar_name"
            if same_phone and similar
            else "same_phone"
            if same_phone
            else "similar_name"
        )
        duplicates.append(Duplicate(patient, reason))
    return duplicates
