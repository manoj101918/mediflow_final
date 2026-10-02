"""Chart read queries. Callers check access first (records.access.chart_patient).

History, medications and vitals come from *finalized* consultations only; the visit being
written today is shown separately as the current draft. Queries are batched per patient
(no N+1).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appointment,
    AppointmentStatus,
    Consultation,
    ConsultationAddendum,
    ConsultationStatus,
    Doctor,
    Patient,
    PatientMedicalProfile,
    PatientReport,
    Prescription,
    PrescriptionItem,
)
from app.services.records.profile import get_profile


@dataclass(frozen=True)
class ChartHeader:
    patient: Patient
    profile: PatientMedicalProfile | None
    visit_count: int
    last_visit: date | None
    # The visit the chart was opened for (?appointment=), if it belongs to this patient.
    appointment: Appointment | None
    appointment_doctor: Doctor | None


async def chart_header(
    session: AsyncSession, patient: Patient, appointment_id: UUID | None
) -> ChartHeader:
    visits = (
        await session.execute(
            select(func.count(), func.max(Appointment.appointment_date)).where(
                Appointment.patient_id == patient.id,
                Appointment.status == AppointmentStatus.COMPLETED,
            )
        )
    ).one()
    appointment: Appointment | None = None
    doctor: Doctor | None = None
    if appointment_id is not None:
        row = (
            await session.execute(
                select(Appointment, Doctor)
                .join(Doctor, Doctor.id == Appointment.doctor_id)
                .where(Appointment.id == appointment_id, Appointment.patient_id == patient.id)
            )
        ).first()
        if row is not None:
            appointment, doctor = row
    return ChartHeader(
        patient=patient,
        profile=await get_profile(session, patient.clinic_id, patient.id),
        visit_count=int(visits[0]),
        last_visit=visits[1],
        appointment=appointment,
        appointment_doctor=doctor,
    )


@dataclass(frozen=True)
class HistoryVisit:
    consultation: Consultation
    visit_date: date
    token_number: int
    doctor_id: UUID
    doctor_name: str
    doctor_specialization: str
    items: list[PrescriptionItem]
    addenda: list[ConsultationAddendum]
    reports: list[PatientReport]


type VisitRow = tuple[Consultation, Appointment, Doctor]


def _finalized_visits(patient_id: UUID) -> Select[Consultation, Appointment, Doctor]:
    return (
        select(Consultation, Appointment, Doctor)
        .join(Appointment, Appointment.id == Consultation.appointment_id)
        .join(Doctor, Doctor.id == Consultation.doctor_id)
        .where(
            Consultation.patient_id == patient_id,
            Consultation.status == ConsultationStatus.FINALIZED,
        )
    )


async def items_by_consultation(
    session: AsyncSession, consultation_ids: list[UUID]
) -> dict[UUID, list[PrescriptionItem]]:
    grouped: dict[UUID, list[PrescriptionItem]] = defaultdict(list)
    if not consultation_ids:
        return grouped
    rows = await session.execute(
        select(Prescription.consultation_id, PrescriptionItem)
        .join(PrescriptionItem, PrescriptionItem.prescription_id == Prescription.id)
        .where(Prescription.consultation_id.in_(consultation_ids))
        .order_by(PrescriptionItem.sort_order, PrescriptionItem.created_at)
    )
    for consultation_id, item in rows:
        grouped[consultation_id].append(item)
    return grouped


async def addenda_by_consultation(
    session: AsyncSession, consultation_ids: list[UUID]
) -> dict[UUID, list[ConsultationAddendum]]:
    grouped: dict[UUID, list[ConsultationAddendum]] = defaultdict(list)
    if not consultation_ids:
        return grouped
    rows = await session.scalars(
        select(ConsultationAddendum)
        .where(ConsultationAddendum.consultation_id.in_(consultation_ids))
        .order_by(ConsultationAddendum.created_at)
    )
    for addendum in rows:
        grouped[addendum.consultation_id].append(addendum)
    return grouped


async def consultation_history(
    session: AsyncSession,
    patient_id: UUID,
    *,
    doctor_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[HistoryVisit]:
    """Every finalized visit (all doctors), newest first."""
    stmt = _finalized_visits(patient_id)
    if doctor_id is not None:
        stmt = stmt.where(Consultation.doctor_id == doctor_id)
    if date_from is not None:
        stmt = stmt.where(Appointment.appointment_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Appointment.appointment_date <= date_to)
    rows = list(
        await session.execute(
            stmt.order_by(Appointment.appointment_date.desc(), Appointment.starts_at.desc())
        )
    )
    ids = [consultation.id for consultation, _, _ in rows]
    items = await items_by_consultation(session, ids)
    addenda = await addenda_by_consultation(session, ids)
    reports: dict[UUID, list[PatientReport]] = defaultdict(list)
    if ids:
        for report in await session.scalars(
            select(PatientReport)
            .where(PatientReport.consultation_id.in_(ids))
            .order_by(PatientReport.created_at)
        ):
            if report.consultation_id is not None:
                reports[report.consultation_id].append(report)
    return [
        HistoryVisit(
            consultation=consultation,
            visit_date=appointment.appointment_date,
            token_number=appointment.token_number,
            doctor_id=doctor.id,
            doctor_name=doctor.full_name,
            doctor_specialization=doctor.specialization,
            items=items.get(consultation.id, []),
            addenda=addenda.get(consultation.id, []),
            reports=reports.get(consultation.id, []),
        )
        for consultation, appointment, doctor in rows
    ]


@dataclass(frozen=True)
class MedicationEntry:
    item: PrescriptionItem
    consultation_id: UUID
    visit_date: date
    doctor_name: str
    # Last day of the course (visit date + duration - 1), if a duration was given.
    end_date: date | None
    current: bool


def course_end(visit_date: date, duration_days: int | None) -> date | None:
    return None if duration_days is None else visit_date + timedelta(days=duration_days - 1)


async def medications(
    session: AsyncSession, patient_id: UUID, today: date
) -> list[MedicationEntry]:
    """All prescribed medicines over time, newest visit first; `current` = course not over."""
    rows = list(
        await session.execute(
            _finalized_visits(patient_id).order_by(
                Appointment.appointment_date.desc(), Appointment.starts_at.desc()
            )
        )
    )
    items = await items_by_consultation(session, [c.id for c, _, _ in rows])
    entries: list[MedicationEntry] = []
    for consultation, appointment, doctor in rows:
        for item in items.get(consultation.id, []):
            end = course_end(appointment.appointment_date, item.duration_days)
            entries.append(
                MedicationEntry(
                    item=item,
                    consultation_id=consultation.id,
                    visit_date=appointment.appointment_date,
                    doctor_name=doctor.full_name,
                    end_date=end,
                    current=end is not None and end >= today,
                )
            )
    return entries


@dataclass(frozen=True)
class VitalsPoint:
    consultation_id: UUID
    visit_date: date
    vitals: dict[str, Any]


async def vitals_series(session: AsyncSession, patient_id: UUID) -> list[VitalsPoint]:
    """Vitals recorded at each finalized visit, oldest first (for trend charts)."""
    rows = await session.execute(
        _finalized_visits(patient_id).order_by(Appointment.appointment_date, Appointment.starts_at)
    )
    return [
        VitalsPoint(consultation.id, appointment.appointment_date, consultation.vitals)
        for consultation, appointment, _ in rows
        if consultation.vitals
    ]


@dataclass(frozen=True)
class LatestPrescription:
    consultation_id: UUID
    visit_date: date
    doctor_name: str
    items: list[PrescriptionItem]


async def latest_prescription(session: AsyncSession, patient_id: UUID) -> LatestPrescription | None:
    """The most recent finalized visit that has prescription items ("Repeat last")."""
    row = (
        await session.execute(
            _finalized_visits(patient_id)
            .where(
                select(PrescriptionItem.id)
                .join(Prescription, Prescription.id == PrescriptionItem.prescription_id)
                .where(Prescription.consultation_id == Consultation.id)
                .exists()
            )
            .order_by(Appointment.appointment_date.desc(), Appointment.starts_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    consultation, appointment, doctor = row
    items = await items_by_consultation(session, [consultation.id])
    return LatestPrescription(
        consultation.id, appointment.appointment_date, doctor.full_name, items[consultation.id]
    )
