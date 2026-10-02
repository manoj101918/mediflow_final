"""Structured patient summary from SQL (not vector search): always source [1].

Name, age, sex, allergies, chronic conditions, current medications (courses not yet over),
last visit, latest abnormal lab values, unacknowledged critical lab results and today's date
in IST, so "current", "allergies" and "since last visit"
questions work even when retrieval finds nothing.
"""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Patient
from app.services.ingestion.render import describe_item, human_date
from app.services.labs.render import lab_summary_lines
from app.services.patients import patient_age
from app.services.records import read
from app.services.records.profile import get_profile


async def patient_summary(session: AsyncSession, patient: Patient, today: date) -> str:
    profile = await get_profile(session, patient.clinic_id, patient.id)
    meds = await read.medications(session, patient.id, today)
    history = await read.consultation_history(session, patient.id)

    age = patient_age(patient, today)
    who = ", ".join(
        part
        for part in (
            patient.full_name,
            patient.gender.value if patient.gender else None,
            f"{age} years" if age is not None else None,
        )
        if part
    )
    lines = [f"Patient: {who}.", f"Today: {human_date(today)} (IST)."]
    if profile is not None:
        lines.append(f"Blood group: {profile.blood_group or 'not recorded'}.")
        lines.append(
            "Allergies: "
            + (", ".join(profile.allergies) if profile.allergies else "none recorded")
            + "."
        )
        lines.append(
            "Chronic conditions: "
            + (", ".join(profile.chronic_conditions) if profile.chronic_conditions else "none")
            + "."
        )
    else:
        lines.append("Allergies: none recorded. Chronic conditions: none recorded.")

    current = [m for m in meds if m.current]
    if current:
        lines.append("Current medications (course not yet finished):")
        lines.extend(
            f"- {describe_item(m.item)}; prescribed {human_date(m.visit_date)} by "
            f"{m.doctor_name}, until {human_date(m.end_date) if m.end_date else 'not stated'}"
            for m in current
        )
    else:
        lines.append("Current medications: none with an unfinished course on record.")

    lines.append(f"Previous finalized visits on record: {len(history)}.")
    if history:
        last = history[0]
        summary = (
            last.consultation.diagnosis
            or last.consultation.chief_complaint
            or "no diagnosis recorded"
        )
        lines.append(
            f"Last visit: {human_date(last.visit_date)} with {last.doctor_name} "
            f"({last.doctor_specialization}): {summary}."
        )
    lines.extend(await lab_summary_lines(session, patient.id, today))
    return "\n".join(lines)
