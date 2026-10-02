from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.results import not_found, unwrap
from app.db.models import Patient
from app.deps import CurrentUser, DbSession, FrontDeskUser, clinic_today
from app.schemas.common import Page
from app.schemas.patients import (
    DuplicateOut,
    PatientCreate,
    PatientDetailOut,
    PatientOut,
    PatientUpdate,
    PatientVisitOut,
)
from app.services import patients as service

router = APIRouter(prefix="/patients", tags=["patients"])


def to_out(patient: Patient, user: CurrentUser) -> PatientOut:
    return PatientOut(
        id=patient.id,
        full_name=patient.full_name,
        phone=patient.phone,
        alternate_phone=patient.alternate_phone,
        gender=patient.gender,
        date_of_birth=patient.date_of_birth,
        age_years=patient.age_years,
        age=service.patient_age(patient, clinic_today(user)),
        address=patient.address,
        notes=patient.notes,
        created_at=patient.created_at,
        updated_at=patient.updated_at,
    )


@router.get("")
async def search_patients(
    session: DbSession,
    user: FrontDeskUser,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[PatientOut]:
    """Search by name (typo-tolerant) or by any part of the phone number."""
    rows, total = await service.search_patients(session, user.clinic_id, q, page, page_size)
    return Page(items=[to_out(p, user) for p in rows], total=total, page=page, page_size=page_size)


@router.get("/duplicates")
async def possible_duplicates(
    session: DbSession,
    user: FrontDeskUser,
    phone: Annotated[str | None, Query(max_length=20)] = None,
    full_name: Annotated[str | None, Query(max_length=120)] = None,
    exclude_id: UUID | None = None,
) -> list[DuplicateOut]:
    """Existing patients matching this phone or a similar name (warn before creating)."""
    matches = await service.find_duplicates(
        session, user.clinic_id, phone=phone, full_name=full_name, exclude_id=exclude_id
    )
    return [DuplicateOut(patient=to_out(m.patient, user), reason=m.reason) for m in matches]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_patient(
    body: PatientCreate, session: DbSession, user: FrontDeskUser
) -> PatientOut:
    patient = unwrap(
        await service.create_patient(session, user.clinic_id, body.model_dump(), user.id)
    )
    return to_out(patient, user)


@router.get("/{patient_id}")
async def get_patient(
    patient_id: UUID, session: DbSession, user: FrontDeskUser
) -> PatientDetailOut:
    patient = await service.get_patient(session, user.clinic_id, patient_id)
    if patient is None:
        raise not_found("Patient")
    history = await service.patient_history(session, patient.id)
    return PatientDetailOut(
        **to_out(patient, user).model_dump(),
        appointments=[
            PatientVisitOut(
                id=a.id,
                starts_at=a.starts_at,
                appointment_date=a.appointment_date,
                token_number=a.token_number,
                status=a.status,
                source=a.source,
                doctor_name=doctor_name,
                reason_for_visit=a.reason_for_visit,
            )
            for a, doctor_name in history
        ],
    )


@router.patch("/{patient_id}")
async def update_patient(
    patient_id: UUID, body: PatientUpdate, session: DbSession, user: FrontDeskUser
) -> PatientOut:
    patient = unwrap(
        await service.update_patient(
            session, user.clinic_id, patient_id, body.model_dump(exclude_unset=True)
        )
    )
    return to_out(patient, user)
