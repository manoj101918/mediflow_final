"""Turn clinical records into readable text pieces for embedding.

Each piece carries its date and who wrote it, so a retrieved chunk stands on its own:
"Visit on 12 Mar 2026 (IST) with Dr. X, General Medicine. Complaint: ... Prescription: ...".
A consultation is normally one piece (prescription and addenda included); the medical
profile is its own piece; reports are split per page in extract/chunking.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appointment,
    Clinic,
    Consultation,
    ConsultationStatus,
    Doctor,
    Patient,
    PatientMedicalProfile,
    PrescriptionItem,
)
from app.services.booking.timeutil import clinic_tz, local_date
from app.services.records.read import addenda_by_consultation, items_by_consultation

TIMING_TEXT = {
    "before_food": "before food",
    "after_food": "after food",
    "with_food": "with food",
    "empty_stomach": "on an empty stomach",
    "bedtime": "at bedtime",
    "any": "at any time",
}


@dataclass(frozen=True)
class Piece:
    """One text piece of a source, before chunking."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RenderedSource:
    clinic_id: UUID
    patient_id: UUID
    source_date: date | None
    # Prefixed to every chunk if the piece has to be split.
    heading: str
    pieces: list[Piece]


def human_date(value: date) -> str:
    """12 Mar 2026"""
    return f"{value.day} {value.strftime('%b %Y')}"


def describe_item(item: PrescriptionItem) -> str:
    parts = [item.medicine_name, item.strength, item.dosage_form]
    text = " ".join(p for p in parts if p)
    if item.dose:
        text += f", dose {item.dose}"
    if item.frequency:
        text += f" {item.frequency}"
    if item.timing:
        text += f" {TIMING_TEXT.get(item.timing, item.timing)}"
    if item.duration_days:
        text += f" for {item.duration_days} day{'s' if item.duration_days != 1 else ''}"
    if item.route:
        text += f" ({item.route})"
    if item.instructions:
        text += f"; {item.instructions}"
    return text


def describe_vitals(vitals: dict[str, Any]) -> str:
    parts = []
    if vitals.get("bp_systolic") and vitals.get("bp_diastolic"):
        parts.append(f"BP {vitals['bp_systolic']}/{vitals['bp_diastolic']} mmHg")
    for key, label, unit in (
        ("pulse", "pulse", "/min"),
        ("temperature_c", "temperature", " °C"),
        ("spo2", "SpO2", "%"),
        ("weight_kg", "weight", " kg"),
        ("height_cm", "height", " cm"),
        ("blood_sugar", "blood sugar", " mg/dL"),
    ):
        if vitals.get(key) is not None:
            parts.append(f"{label} {vitals[key]}{unit}")
    return ", ".join(parts)


async def render_consultation(
    session: AsyncSession, consultation_id: UUID
) -> RenderedSource | None:
    """A finalized visit as one text piece; None if it is missing or still a draft."""
    row = (
        await session.execute(
            select(Consultation, Appointment, Doctor)
            .join(Appointment, Appointment.id == Consultation.appointment_id)
            .join(Doctor, Doctor.id == Consultation.doctor_id)
            .where(Consultation.id == consultation_id)
        )
    ).first()
    if row is None:
        return None
    consultation, appointment, doctor = row
    if consultation.status is not ConsultationStatus.FINALIZED:
        return None
    items = (await items_by_consultation(session, [consultation.id])).get(consultation.id, [])
    addenda = (await addenda_by_consultation(session, [consultation.id])).get(consultation.id, [])

    visit_date = appointment.appointment_date
    heading = (
        f"Visit on {human_date(visit_date)} (IST) with {doctor.full_name}, {doctor.specialization}."
    )
    lines = [heading]
    if appointment.reason_for_visit:
        lines.append(f"Reason for visit: {appointment.reason_for_visit}.")
    for label, value in (
        ("Complaint", consultation.chief_complaint),
        ("History", consultation.history),
        ("Examination", consultation.examination),
        ("Diagnosis", consultation.diagnosis),
    ):
        if value:
            lines.append(f"{label}: {value.strip()}")
    vitals = describe_vitals(consultation.vitals)
    if vitals:
        lines.append(f"Vitals: {vitals}.")
    if items:
        lines.append(
            "Prescription: "
            + "; ".join(f"{i}) {describe_item(item)}" for i, item in enumerate(items, start=1))
            + "."
        )
    else:
        lines.append("Prescription: none.")
    for label, value in (("Advice", consultation.advice), ("Notes", consultation.notes)):
        if value:
            lines.append(f"{label}: {value.strip()}")
    if consultation.follow_up_date:
        lines.append(f"Follow-up: {human_date(consultation.follow_up_date)}.")
    tz = clinic_tz()
    for addendum in addenda:
        written = human_date(local_date(addendum.created_at, tz))
        lines.append(f"Addendum on {written} by {addendum.author_name}: {addendum.text}")

    metadata = {
        "doctor_name": doctor.full_name,
        "specialization": doctor.specialization,
        "visit_date": visit_date.isoformat(),
        "label": f"Visit {human_date(visit_date)}, {doctor.full_name}",
    }
    return RenderedSource(
        clinic_id=consultation.clinic_id,
        patient_id=consultation.patient_id,
        source_date=visit_date,
        heading=f"{heading} (continued)",
        pieces=[Piece("\n".join(lines), metadata)],
    )


async def render_profile(session: AsyncSession, patient_id: UUID) -> RenderedSource | None:
    """The medical profile as its own piece; None if there is no profile."""
    row = (
        await session.execute(
            select(PatientMedicalProfile, Patient, Clinic.timezone)
            .join(Patient, Patient.id == PatientMedicalProfile.patient_id)
            .join(Clinic, Clinic.id == Patient.clinic_id)
            .where(PatientMedicalProfile.patient_id == patient_id)
        )
    ).first()
    if row is None:
        return None
    profile, patient, timezone = row
    updated = local_date(profile.updated_at, clinic_tz(timezone))
    allergies = ", ".join(profile.allergies) if profile.allergies else "none recorded"
    conditions = (
        ", ".join(profile.chronic_conditions) if profile.chronic_conditions else "none recorded"
    )
    content = (
        f"Medical profile of {patient.full_name} (updated {human_date(updated)}). "
        f"Blood group: {profile.blood_group or 'not recorded'}. "
        f"Allergies: {allergies}. Chronic conditions: {conditions}."
    )
    return RenderedSource(
        clinic_id=patient.clinic_id,
        patient_id=patient.id,
        source_date=updated,
        heading="Medical profile (continued)",
        pieces=[Piece(content, {"label": "Medical profile", "updated": updated.isoformat()})],
    )
