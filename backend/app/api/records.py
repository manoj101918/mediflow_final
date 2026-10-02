"""Doctor chart: header, medical profile, current visit, history, medications, vitals.

Access rules live in app/services/records (any clinic doctor reads any clinic patient; only the
appointment's own doctor writes; reception/admin get 403).
"""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.results import unwrap
from app.db.models import (
    ConsultationAddendum,
    ConsultationStatus,
    PatientMedicalProfile,
    PatientReport,
    PrescriptionItem,
    RecordAccessAction,
)
from app.deps import AuthUser, CurrentUser, DbSession, clinic_today, staff_actor
from app.schemas.records import (
    AddendumIn,
    AddendumOut,
    ChartAppointmentOut,
    ChartOut,
    CompleteOut,
    ConsultationIn,
    ConsultationOut,
    HistoryVisitOut,
    LatestPrescriptionOut,
    MedicalProfileIn,
    MedicalProfileOut,
    MedicationOut,
    PrescriptionItemOut,
    ReportBriefOut,
    VisitOut,
    Vitals,
    VitalsPointOut,
)
from app.services.patients import patient_age
from app.services.records import read
from app.services.records.access import chart_patient
from app.services.records.audit import record_access
from app.services.records.consultations import (
    EDITABLE_STATUSES,
    ConsultationInput,
    ItemInput,
    Visit,
    add_addendum,
    complete_visit,
    get_visit,
    save_draft,
)
from app.services.records.profile import update_profile

router = APIRouter(tags=["records"])


def item_out(item: PrescriptionItem) -> PrescriptionItemOut:
    return PrescriptionItemOut(
        id=item.id,
        medicine_name=item.medicine_name,
        strength=item.strength,
        dosage_form=item.dosage_form,
        dose=item.dose,
        route=item.route,
        frequency=item.frequency,
        timing=item.timing,
        duration_days=item.duration_days,
        instructions=item.instructions,
        sort_order=item.sort_order,
    )


def addendum_out(addendum: ConsultationAddendum) -> AddendumOut:
    return AddendumOut(
        id=addendum.id,
        consultation_id=addendum.consultation_id,
        author_name=addendum.author_name,
        text=addendum.text,
        created_at=addendum.created_at,
    )


def report_brief(report: PatientReport) -> ReportBriefOut:
    return ReportBriefOut(
        id=report.id,
        title=report.title,
        report_type=report.report_type,
        report_date=report.report_date,
        mime_type=report.mime_type,
        ingestion_status=report.ingestion_status,
    )


def profile_out(profile: PatientMedicalProfile | None) -> MedicalProfileOut:
    if profile is None:
        return MedicalProfileOut(
            blood_group=None, allergies=[], chronic_conditions=[], updated_at=None
        )
    return MedicalProfileOut(
        blood_group=profile.blood_group,
        allergies=list(profile.allergies),
        chronic_conditions=list(profile.chronic_conditions),
        updated_at=profile.updated_at,
    )


def visit_out(visit: Visit, user: CurrentUser) -> VisitOut:
    appointment, consultation = visit.appointment, visit.consultation
    editable = (
        appointment.doctor_id == user.doctor_id
        and appointment.status in EDITABLE_STATUSES
        and (consultation is None or consultation.status is ConsultationStatus.DRAFT)
    )
    return VisitOut(
        appointment_id=appointment.id,
        appointment_status=appointment.status,
        doctor_id=appointment.doctor_id,
        editable=editable,
        consultation=None
        if consultation is None
        else ConsultationOut(
            id=consultation.id,
            appointment_id=consultation.appointment_id,
            patient_id=consultation.patient_id,
            doctor_id=consultation.doctor_id,
            chief_complaint=consultation.chief_complaint,
            history=consultation.history,
            examination=consultation.examination,
            diagnosis=consultation.diagnosis,
            advice=consultation.advice,
            follow_up_date=consultation.follow_up_date,
            notes=consultation.notes,
            vitals=Vitals.model_validate(consultation.vitals),
            status=consultation.status,
            finalized_at=consultation.finalized_at,
            created_at=consultation.created_at,
            updated_at=consultation.updated_at,
            items=[item_out(i) for i in visit.items],
        ),
    )


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------


@router.get("/patients/{patient_id}/chart")
async def get_chart(
    patient_id: UUID, session: DbSession, user: AuthUser, appointment: UUID | None = None
) -> ChartOut:
    """Chart header. Every open is written to the access log."""
    actor = staff_actor(user)
    patient = unwrap(await chart_patient(session, actor, patient_id))
    header = await read.chart_header(session, patient, appointment)
    await record_access(
        session,
        actor,
        patient.id,
        RecordAccessAction.CHART_OPEN,
        appointment_id=header.appointment.id if header.appointment else None,
    )
    current = header.appointment
    return ChartOut(
        patient_id=patient.id,
        full_name=patient.full_name,
        gender=patient.gender,
        age=patient_age(patient, clinic_today(user)),
        date_of_birth=patient.date_of_birth,
        profile=profile_out(header.profile),
        visit_count=header.visit_count,
        last_visit=header.last_visit,
        appointment=None
        if current is None or header.appointment_doctor is None
        else ChartAppointmentOut(
            id=current.id,
            token_number=current.token_number,
            status=current.status,
            starts_at=current.starts_at,
            appointment_date=current.appointment_date,
            reason_for_visit=current.reason_for_visit,
            doctor_id=current.doctor_id,
            doctor_name=header.appointment_doctor.full_name,
        ),
    )


@router.put("/patients/{patient_id}/medical-profile")
async def put_medical_profile(
    patient_id: UUID, body: MedicalProfileIn, session: DbSession, user: AuthUser
) -> MedicalProfileOut:
    profile = unwrap(
        await update_profile(
            session,
            staff_actor(user),
            patient_id,
            blood_group=body.blood_group,
            allergies=body.allergies,
            chronic_conditions=body.chronic_conditions,
        )
    )
    return profile_out(profile)


@router.get("/patients/{patient_id}/consultations")
async def list_consultations(
    patient_id: UUID,
    session: DbSession,
    user: AuthUser,
    doctor_id: UUID | None = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> list[HistoryVisitOut]:
    """Every finalized visit across all doctors, newest first."""
    patient = unwrap(await chart_patient(session, staff_actor(user), patient_id))
    visits = await read.consultation_history(
        session, patient.id, doctor_id=doctor_id, date_from=date_from, date_to=date_to
    )
    return [
        HistoryVisitOut(
            consultation_id=v.consultation.id,
            appointment_id=v.consultation.appointment_id,
            visit_date=v.visit_date,
            token_number=v.token_number,
            doctor_id=v.doctor_id,
            doctor_name=v.doctor_name,
            doctor_specialization=v.doctor_specialization,
            chief_complaint=v.consultation.chief_complaint,
            history=v.consultation.history,
            examination=v.consultation.examination,
            diagnosis=v.consultation.diagnosis,
            advice=v.consultation.advice,
            follow_up_date=v.consultation.follow_up_date,
            notes=v.consultation.notes,
            vitals=Vitals.model_validate(v.consultation.vitals),
            finalized_at=v.consultation.finalized_at,
            items=[item_out(i) for i in v.items],
            addenda=[addendum_out(a) for a in v.addenda],
            reports=[report_brief(r) for r in v.reports],
        )
        for v in visits
    ]


@router.get("/patients/{patient_id}/medications")
async def list_medications(
    patient_id: UUID, session: DbSession, user: AuthUser
) -> list[MedicationOut]:
    patient = unwrap(await chart_patient(session, staff_actor(user), patient_id))
    entries = await read.medications(session, patient.id, clinic_today(user))
    return [
        MedicationOut(
            item=item_out(e.item),
            consultation_id=e.consultation_id,
            visit_date=e.visit_date,
            doctor_name=e.doctor_name,
            end_date=e.end_date,
            current=e.current,
        )
        for e in entries
    ]


@router.get("/patients/{patient_id}/vitals")
async def list_vitals(patient_id: UUID, session: DbSession, user: AuthUser) -> list[VitalsPointOut]:
    patient = unwrap(await chart_patient(session, staff_actor(user), patient_id))
    return [
        VitalsPointOut(
            consultation_id=p.consultation_id,
            visit_date=p.visit_date,
            vitals=Vitals.model_validate(p.vitals),
        )
        for p in await read.vitals_series(session, patient.id)
    ]


@router.get("/patients/{patient_id}/prescriptions/latest")
async def latest_prescription(
    patient_id: UUID, session: DbSession, user: AuthUser
) -> LatestPrescriptionOut | None:
    """The last finalized prescription, for "Repeat last prescription"."""
    patient = unwrap(await chart_patient(session, staff_actor(user), patient_id))
    latest = await read.latest_prescription(session, patient.id)
    if latest is None:
        return None
    return LatestPrescriptionOut(
        consultation_id=latest.consultation_id,
        visit_date=latest.visit_date,
        doctor_name=latest.doctor_name,
        items=[item_out(i) for i in latest.items],
    )


# ---------------------------------------------------------------------------
# Current visit
# ---------------------------------------------------------------------------


@router.get("/appointments/{appointment_id}/consultation")
async def get_consultation(appointment_id: UUID, session: DbSession, user: AuthUser) -> VisitOut:
    return visit_out(unwrap(await get_visit(session, staff_actor(user), appointment_id)), user)


@router.put("/appointments/{appointment_id}/consultation")
async def put_consultation(
    appointment_id: UUID, body: ConsultationIn, session: DbSession, user: AuthUser
) -> VisitOut:
    """Autosave the draft. Only fields present in the body change; `items` replaces the list."""
    fields = body.model_dump(exclude_unset=True, exclude={"items", "vitals"})
    if "vitals" in body.model_fields_set:
        fields["vitals"] = body.vitals.model_dump(exclude_none=True) if body.vitals else {}
    items = None if body.items is None else [ItemInput(**item.model_dump()) for item in body.items]
    visit = unwrap(
        await save_draft(
            session, staff_actor(user), appointment_id, ConsultationInput(fields, items)
        )
    )
    return visit_out(visit, user)


@router.post("/appointments/{appointment_id}/complete")
async def complete(appointment_id: UUID, session: DbSession, user: AuthUser) -> CompleteOut:
    """Complete the appointment and finalize its draft consultation (one transaction)."""
    done = unwrap(await complete_visit(session, staff_actor(user), appointment_id))
    return CompleteOut(
        appointment_id=done.appointment.id,
        appointment_status=done.appointment.status,
        consultation_id=done.consultation.id if done.consultation else None,
        finalized=done.consultation is not None
        and done.consultation.status is ConsultationStatus.FINALIZED,
    )


@router.post("/consultations/{consultation_id}/addenda", status_code=status.HTTP_201_CREATED)
async def create_addendum(
    consultation_id: UUID, body: AddendumIn, session: DbSession, user: AuthUser
) -> AddendumOut:
    return addendum_out(
        unwrap(await add_addendum(session, staff_actor(user), consultation_id, body.text))
    )
