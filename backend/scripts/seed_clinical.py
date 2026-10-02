"""Seed synthetic (fake) clinical history for the demo clinic, then index it for the chatbot.

    cd backend
    uv run python -m scripts.seed_clinical            # real providers (VOYAGE_API_KEY)
    RAG_FAKE_LLM=true uv run python -m scripts.seed_clinical   # fake embeddings, no keys

Run after supabase/seed.sql and scripts.seed_users. Adds to the seed data only: past completed
appointments (fixed dates, Dec 2025 - Sep 2026), finalized consultations with prescriptions,
addenda, medical profiles and text-based lab PDFs (uploaded to the patient-reports bucket).
Idempotent: every row has a fixed id and existing rows are left untouched.

Test patient for the assistant: Prakash Hegde - type 2 diabetes with HbA1c 8.1 -> 7.4 -> 6.9,
penicillin allergy, glimepiride added in March and stopped in September.
"""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from anyio import to_thread
from fpdf import FPDF
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RecordSourceType
from app.db.session import dispose_engine, get_sessionmaker
from app.services.booking.timeutil import clinic_tz
from app.services.ingestion.jobs import enqueue
from app.services.ingestion.worker import default_deps, run_pending
from app.services.rag.providers import ProviderNotConfiguredError
from app.services.records.storage import get_report_storage, report_path

CLINIC = uuid.UUID("11111111-1111-4111-8111-111111111111")
DR_SHARMA = uuid.UUID("d0c00000-0000-4000-8000-000000000001")  # General Physician
DR_IYER = uuid.UUID("d0c00000-0000-4000-8000-000000000002")  # Pediatrician
DR_KHAN = uuid.UUID("d0c00000-0000-4000-8000-000000000003")  # Orthopedics

PRAKASH = uuid.UUID("2037da99-bae2-d71e-a051-2f8a85bb826f")
RAVI = uuid.UUID("b8504f2a-013a-51ed-87ef-03c526cf5e0d")
LAKSHMI = uuid.UUID("0fbffa1b-5745-34d3-4fa6-e71008cab14b")
RAJESH = uuid.UUID("000c60fd-f4af-106f-94d3-39c270e1a34a")
ANANYA = uuid.UUID("3a2d238e-2ae8-1a5a-44ca-d67fc14cdbdb")

NAMESPACE = uuid.UUID("6f1d0c9e-5b0a-4c4e-9a43-6d0a2c1f0b77")


def sid(*parts: object) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, "/".join(str(p) for p in parts))


# --- The synthetic records --------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    medicine: str
    strength: str | None
    form: str
    frequency: str
    timing: str | None
    days: int | None
    instructions: str | None = None


@dataclass(frozen=True)
class Visit:
    key: str
    day: date
    at: time
    doctor: uuid.UUID
    reason: str
    complaint: str
    diagnosis: str
    history: str | None = None
    examination: str | None = None
    advice: str | None = None
    vitals: dict[str, Any] = field(default_factory=dict)
    items: tuple[Item, ...] = ()
    follow_up: date | None = None
    addendum: tuple[str, str] | None = None  # (author full name, text)


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    report_type: str
    day: date
    lines: tuple[str, ...]
    visit_key: str | None = None


@dataclass(frozen=True)
class PatientRecords:
    patient: uuid.UUID
    blood_group: str
    allergies: tuple[str, ...]
    conditions: tuple[str, ...]
    visits: tuple[Visit, ...]
    reports: tuple[Report, ...]


METFORMIN_500 = Item("Metformin", "500 mg", "tablet", "1-0-1", "after_food", 90)
METFORMIN_1000 = Item("Metformin", "1000 mg", "tablet", "1-0-1", "after_food", 90)
TELMISARTAN = Item("Telmisartan", "40 mg", "tablet", "1-0-0", "after_food", 90)
GLIMEPIRIDE = Item(
    "Glimepiride", "1 mg", "tablet", "1-0-0", "before_food", 90, "15 minutes before breakfast"
)

RECORDS: tuple[PatientRecords, ...] = (
    PatientRecords(
        patient=PRAKASH,
        blood_group="B+",
        allergies=("Penicillin",),
        conditions=("Type 2 diabetes mellitus", "Hypertension"),
        visits=(
            Visit(
                "prakash-1",
                date(2025, 12, 8),
                time(10, 0),
                DR_SHARMA,
                "Tiredness and thirst",
                "Increased thirst, frequent urination and tiredness for 2 months.",
                "Type 2 diabetes mellitus, newly diagnosed (HbA1c 8.1%). Stage 1 hypertension.",
                history="Father had diabetes. Rash with amoxicillin (penicillin) in 2019.",
                examination="Overweight. No foot ulcers. Peripheral pulses normal.",
                advice="Diabetic diet, walk 30 minutes daily, reduce salt. Home sugar log.",
                vitals={
                    "bp_systolic": 142,
                    "bp_diastolic": 90,
                    "pulse": 82,
                    "weight_kg": 84,
                    "height_cm": 170,
                    "blood_sugar": 212,
                },
                items=(METFORMIN_500, TELMISARTAN),
                follow_up=date(2026, 3, 10),
            ),
            Visit(
                "prakash-2",
                date(2026, 3, 12),
                time(10, 15),
                DR_SHARMA,
                "Diabetes review",
                "Review with HbA1c report. Occasional evening fatigue.",
                "Type 2 diabetes mellitus, improving but above target (HbA1c 7.4%). "
                "Hypertension controlled.",
                examination="Weight down 3 kg. Feet normal.",
                advice="Continue diet and walking. Carry glucose tablets in case of low sugar.",
                vitals={
                    "bp_systolic": 136,
                    "bp_diastolic": 86,
                    "pulse": 78,
                    "weight_kg": 81,
                    "blood_sugar": 168,
                },
                items=(METFORMIN_1000, GLIMEPIRIDE, TELMISARTAN),
                follow_up=date(2026, 6, 15),
                addendum=(
                    "Dr. Anil Sharma",
                    "Phone follow-up 20 Mar 2026: mild stomach upset after the metformin increase; "
                    "advised to always take it after meals. Continue same doses.",
                ),
            ),
            Visit(
                "prakash-3",
                date(2026, 6, 18),
                time(11, 0),
                DR_KHAN,
                "Right knee pain",
                "Right knee pain for 6 weeks, worse on climbing stairs.",
                "Early osteoarthritis of the right knee.",
                examination="Mild crepitus right knee, no effusion, full range of movement.",
                advice="Quadriceps strengthening exercises. Avoid squatting. "
                "NSAIDs avoided because of diabetes and hypertension.",
                vitals={"bp_systolic": 132, "bp_diastolic": 84, "weight_kg": 80},
                items=(
                    Item(
                        "Paracetamol",
                        "650 mg",
                        "tablet",
                        "SOS",
                        "after_food",
                        10,
                        "For knee pain, at most 3 tablets a day",
                    ),
                ),
            ),
            Visit(
                "prakash-4",
                date(2026, 9, 15),
                time(10, 30),
                DR_SHARMA,
                "Diabetes review",
                "Two episodes of shakiness and sweating before lunch in August "
                "(home sugar 62 and 66 mg/dL).",
                "Type 2 diabetes mellitus at target (HbA1c 6.9%). Hypoglycaemia on glimepiride.",
                advice="Glimepiride stopped because of hypoglycaemia. Continue metformin and "
                "telmisartan. Repeat HbA1c and lipid profile in 3 months.",
                vitals={
                    "bp_systolic": 130,
                    "bp_diastolic": 84,
                    "pulse": 76,
                    "weight_kg": 79,
                    "blood_sugar": 128,
                },
                items=(METFORMIN_1000, TELMISARTAN),
                follow_up=date(2026, 12, 15),
            ),
        ),
        reports=(
            Report(
                "prakash-lab-1",
                "HbA1c and blood sugar",
                "lab",
                date(2025, 12, 6),
                (
                    "Glycated haemoglobin (HbA1c): 8.1 %   (target < 7.0 %)",
                    "Fasting blood glucose: 168 mg/dL   (70 - 99)",
                    "Post-prandial blood glucose: 246 mg/dL   (< 140)",
                    "Serum creatinine: 0.9 mg/dL   (0.7 - 1.3)",
                ),
                "prakash-1",
            ),
            Report(
                "prakash-lab-2",
                "HbA1c",
                "lab",
                date(2026, 3, 10),
                (
                    "Glycated haemoglobin (HbA1c): 7.4 %   (target < 7.0 %)",
                    "Fasting blood glucose: 138 mg/dL   (70 - 99)",
                ),
                "prakash-2",
            ),
            Report(
                "prakash-lab-3",
                "HbA1c and lipid profile",
                "lab",
                date(2026, 9, 12),
                (
                    "Glycated haemoglobin (HbA1c): 6.9 %   (target < 7.0 %)",
                    "Fasting blood glucose: 112 mg/dL   (70 - 99)",
                    "Total cholesterol: 186 mg/dL   (< 200)",
                    "LDL cholesterol: 118 mg/dL   (< 100)",
                    "HDL cholesterol: 42 mg/dL   (> 40)",
                    "Triglycerides: 160 mg/dL   (< 150)",
                    "Urine microalbumin: 18 mg/g creatinine   (< 30)",
                ),
                "prakash-4",
            ),
        ),
    ),
    PatientRecords(
        patient=RAVI,
        blood_group="O+",
        allergies=("Sulfa drugs",),
        conditions=("Bronchial asthma",),
        visits=(
            Visit(
                "ravi-1",
                date(2026, 1, 20),
                time(17, 30),
                DR_SHARMA,
                "Cough and fever",
                "Dry cough and low-grade fever for 4 days.",
                "Acute upper respiratory infection.",
                vitals={"temperature_c": 38.1, "pulse": 96, "spo2": 97, "weight_kg": 72},
                items=(
                    Item("Paracetamol", "650 mg", "tablet", "1-1-1", "after_food", 3),
                    Item("Levocetirizine", "5 mg", "tablet", "0-0-1", "bedtime", 5),
                ),
                advice="Steam inhalation, fluids. Return if breathless.",
            ),
            Visit(
                "ravi-2",
                date(2026, 4, 5),
                time(18, 0),
                DR_SHARMA,
                "Wheezing",
                "Wheezing and breathlessness at night for a week after dust exposure.",
                "Acute exacerbation of bronchial asthma (mild).",
                examination="Bilateral expiratory wheeze. SpO2 95% on room air.",
                vitals={"pulse": 102, "spo2": 95, "weight_kg": 72},
                items=(
                    Item(
                        "Salbutamol",
                        "100 mcg",
                        "inhaler",
                        "SOS",
                        None,
                        30,
                        "2 puffs when breathless",
                    ),
                    Item(
                        "Budesonide/Formoterol",
                        "200/6 mcg",
                        "inhaler",
                        "1-0-1",
                        None,
                        30,
                        "Rinse mouth after use",
                    ),
                ),
                advice="Avoid dust, use a mask while cleaning.",
                follow_up=date(2026, 5, 5),
            ),
            Visit(
                "ravi-3",
                date(2026, 8, 22),
                time(11, 20),
                DR_KHAN,
                "Low back pain",
                "Low back pain after lifting a heavy box, 5 days.",
                "Acute lumbar muscle strain.",
                examination="Paraspinal tenderness, straight leg raise negative.",
                items=(
                    Item("Thiocolchicoside", "4 mg", "tablet", "1-0-1", "after_food", 5),
                    Item("Diclofenac gel", None, "gel", "1-1-1", None, 7, "Apply locally"),
                ),
                advice="Hot fomentation, back exercises after pain settles.",
            ),
        ),
        reports=(
            Report(
                "ravi-xray",
                "Chest X-ray",
                "imaging",
                date(2026, 4, 5),
                (
                    "Chest X-ray PA view",
                    "Lungs: hyperinflated, no consolidation or effusion.",
                    "Heart size normal. Costophrenic angles clear.",
                    "Impression: features consistent with obstructive airway disease; "
                    "no pneumonia.",
                ),
                "ravi-2",
            ),
        ),
    ),
    PatientRecords(
        patient=LAKSHMI,
        blood_group="A+",
        allergies=(),
        conditions=("Hypothyroidism", "Osteopenia"),
        visits=(
            Visit(
                "lakshmi-1",
                date(2026, 2, 3),
                time(10, 45),
                DR_SHARMA,
                "Thyroid follow-up",
                "Tiredness and weight gain.",
                "Primary hypothyroidism, under-replaced (TSH 8.2).",
                vitals={"bp_systolic": 128, "bp_diastolic": 80, "weight_kg": 66},
                items=(Item("Levothyroxine", "75 mcg", "tablet", "1-0-0", "empty_stomach", 60),),
                follow_up=date(2026, 4, 3),
            ),
            Visit(
                "lakshmi-2",
                date(2026, 4, 7),
                time(10, 0),
                DR_SHARMA,
                "Thyroid review",
                "Feels better.",
                "Hypothyroidism, controlled (TSH 3.1).",
                vitals={"bp_systolic": 126, "bp_diastolic": 78, "weight_kg": 64},
                items=(
                    Item("Levothyroxine", "75 mcg", "tablet", "1-0-0", "empty_stomach", 180),
                    Item(
                        "Calcium carbonate + Vitamin D3",
                        "500 mg/250 IU",
                        "tablet",
                        "0-1-0",
                        "after_food",
                        180,
                    ),
                ),
            ),
            Visit(
                "lakshmi-3",
                date(2026, 7, 14),
                time(16, 30),
                DR_KHAN,
                "Wrist pain",
                "Pain in the left wrist after a fall at home.",
                "Left wrist sprain; no fracture.",
                examination="Tenderness over the radial side, X-ray normal.",
                items=(Item("Paracetamol", "500 mg", "tablet", "1-0-1", "after_food", 5),),
                advice="Wrist splint for 2 weeks. DEXA scan advised (osteopenia).",
            ),
        ),
        reports=(
            Report(
                "lakshmi-thyroid",
                "Thyroid profile",
                "lab",
                date(2026, 4, 4),
                (
                    "TSH: 3.1 mIU/L   (0.4 - 4.0)",
                    "Free T4: 1.2 ng/dL   (0.8 - 1.8)",
                    "Previous TSH (31 Jan 2026): 8.2 mIU/L",
                ),
                "lakshmi-2",
            ),
        ),
    ),
    PatientRecords(
        patient=RAJESH,
        blood_group="AB+",
        allergies=("Aspirin",),
        conditions=("Hypertension", "Dyslipidaemia"),
        visits=(
            Visit(
                "rajesh-1",
                date(2026, 1, 12),
                time(9, 30),
                DR_SHARMA,
                "Headache",
                "Morning headaches for 2 weeks.",
                "Essential hypertension, newly diagnosed.",
                vitals={"bp_systolic": 156, "bp_diastolic": 98, "pulse": 84, "weight_kg": 88},
                items=(Item("Amlodipine", "5 mg", "tablet", "1-0-0", "after_food", 30),),
                advice="Low salt diet. Home BP log.",
                follow_up=date(2026, 2, 12),
            ),
            Visit(
                "rajesh-2",
                date(2026, 2, 16),
                time(9, 45),
                DR_SHARMA,
                "BP review",
                "BP log 140-150 / 90.",
                "Hypertension, partially controlled. Dyslipidaemia.",
                vitals={"bp_systolic": 144, "bp_diastolic": 92, "weight_kg": 87},
                items=(
                    Item("Amlodipine", "10 mg", "tablet", "1-0-0", "after_food", 90),
                    Item("Atorvastatin", "20 mg", "tablet", "0-0-1", "bedtime", 90),
                ),
            ),
            Visit(
                "rajesh-3",
                date(2026, 5, 25),
                time(10, 0),
                DR_SHARMA,
                "BP review",
                "Ankle swelling in the evenings.",
                "Hypertension controlled; ankle oedema due to amlodipine.",
                vitals={"bp_systolic": 128, "bp_diastolic": 82, "weight_kg": 85},
                items=(
                    Item("Telmisartan", "40 mg", "tablet", "1-0-0", "after_food", 90),
                    Item("Atorvastatin", "20 mg", "tablet", "0-0-1", "bedtime", 90),
                ),
                advice="Amlodipine stopped (ankle oedema), switched to telmisartan.",
            ),
        ),
        reports=(
            Report(
                "rajesh-lipid",
                "Lipid profile",
                "lab",
                date(2026, 2, 14),
                (
                    "Total cholesterol: 238 mg/dL   (< 200)",
                    "LDL cholesterol: 162 mg/dL   (< 100)",
                    "HDL cholesterol: 38 mg/dL   (> 40)",
                    "Triglycerides: 210 mg/dL   (< 150)",
                ),
                "rajesh-2",
            ),
        ),
    ),
    PatientRecords(
        patient=ANANYA,
        blood_group="O-",
        allergies=("Peanuts",),
        conditions=("Allergic rhinitis",),
        visits=(
            Visit(
                "ananya-1",
                date(2026, 1, 9),
                time(11, 0),
                DR_IYER,
                "Sneezing",
                "Sneezing and blocked nose every morning for a month.",
                "Allergic rhinitis.",
                vitals={"weight_kg": 27, "height_cm": 128, "temperature_c": 36.8},
                items=(
                    Item(
                        "Cetirizine syrup",
                        "5 mg/5 mL",
                        "syrup",
                        "0-0-1",
                        "bedtime",
                        10,
                        "5 mL at night",
                    ),
                    Item("Saline nasal spray", None, "nasal spray", "1-1-1", None, 14),
                ),
            ),
            Visit(
                "ananya-2",
                date(2026, 5, 2),
                time(11, 30),
                DR_IYER,
                "Fever",
                "Fever and sore throat for 2 days.",
                "Acute viral pharyngitis.",
                vitals={"weight_kg": 28, "temperature_c": 38.4},
                items=(
                    Item(
                        "Paracetamol syrup",
                        "250 mg/5 mL",
                        "syrup",
                        "SOS",
                        None,
                        3,
                        "7.5 mL if temperature above 38.5 °C",
                    ),
                ),
                advice="Plenty of fluids; return if fever lasts more than 3 days.",
            ),
            Visit(
                "ananya-3",
                date(2026, 8, 28),
                time(10, 30),
                DR_IYER,
                "Growth check",
                "Routine growth check before school year.",
                "Healthy child, growth normal.",
                vitals={"weight_kg": 29, "height_cm": 132},
            ),
        ),
        reports=(
            Report(
                "ananya-cbc",
                "Complete blood count",
                "lab",
                date(2026, 5, 3),
                (
                    "Haemoglobin: 12.1 g/dL   (11.5 - 15.5)",
                    "Total leucocyte count: 11,800 /uL   (4,500 - 13,500)",
                    "Platelets: 2.6 lakh /uL   (1.5 - 4.5)",
                ),
                "ananya-2",
            ),
        ),
    ),
)


# --- Writing ------------------------------------------------------------------------------------


def lab_pdf(report: Report, patient_name: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "MediFlow Diagnostics (synthetic demo report)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 8, f"Patient: {patient_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Report: {report.title}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Date: {report.day.strftime('%d %b %Y')}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    for line in report.lines:
        pdf.multi_cell(0, 7, line, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(0, 5, "Synthetic data generated for the MediFlow demo. Not a real patient.")
    return bytes(pdf.output())


async def _exists(session: AsyncSession, table: str, row_id: uuid.UUID) -> bool:
    found = await session.scalar(
        text(f"select 1 from public.{table} where id = :id"),  # noqa: S608 - fixed table names
        {"id": row_id},
    )
    return found is not None


async def seed_visit(
    session: AsyncSession, patient: uuid.UUID, visit: Visit, token: int
) -> uuid.UUID | None:
    """Completed appointment + finalized consultation (+ prescription, addendum)."""
    appointment_id, consultation_id = sid("appt", visit.key), sid("consultation", visit.key)
    if await _exists(session, "consultations", consultation_id):
        return None
    starts = datetime.combine(visit.day, visit.at, tzinfo=clinic_tz()).astimezone(UTC)
    await session.execute(
        text(
            "insert into public.appointments (id, clinic_id, patient_id, doctor_id, starts_at, "
            "ends_at, status, source, token_number, reason_for_visit) values (:id, :clinic, "
            ":patient, :doctor, :starts, :ends, 'completed', 'walk_in', :token, :reason) "
            "on conflict (id) do nothing"
        ),
        {
            "id": appointment_id,
            "clinic": CLINIC,
            "patient": patient,
            "doctor": visit.doctor,
            "starts": starts,
            "ends": starts + timedelta(minutes=15),
            "token": token,
            "reason": visit.reason,
        },
    )
    await session.execute(
        text(
            "insert into public.consultations (id, clinic_id, appointment_id, patient_id, "
            "doctor_id, chief_complaint, history, examination, diagnosis, advice, "
            "follow_up_date, vitals, status, finalized_at, created_at) values (:id, :clinic, "
            ":appt, :patient, :doctor, :complaint, :history, :exam, :dx, :advice, :follow, "
            "cast(:vitals as jsonb), 'draft', null, :done)"
        ),
        {
            "id": consultation_id,
            "clinic": CLINIC,
            "appt": appointment_id,
            "patient": patient,
            "doctor": visit.doctor,
            "complaint": visit.complaint,
            "history": visit.history,
            "exam": visit.examination,
            "dx": visit.diagnosis,
            "advice": visit.advice,
            "follow": visit.follow_up,
            "vitals": json.dumps(visit.vitals),
            "done": starts + timedelta(minutes=14),
        },
    )
    if visit.items:
        prescription_id = sid("prescription", visit.key)
        await session.execute(
            text(
                "insert into public.prescriptions (id, clinic_id, consultation_id, patient_id) "
                "values (:id, :clinic, :consultation, :patient)"
            ),
            {
                "id": prescription_id,
                "clinic": CLINIC,
                "consultation": consultation_id,
                "patient": patient,
            },
        )
        for order, item in enumerate(visit.items):
            await session.execute(
                text(
                    "insert into public.prescription_items (id, prescription_id, medicine_name, "
                    "strength, dosage_form, frequency, timing, duration_days, instructions, "
                    "sort_order) values (:id, :rx, :name, :strength, :form, :freq, :timing, "
                    ":days, :instr, :order)"
                ),
                {
                    "id": sid("item", visit.key, order),
                    "rx": prescription_id,
                    "name": item.medicine,
                    "strength": item.strength,
                    "form": item.form,
                    "freq": item.frequency,
                    "timing": item.timing,
                    "days": item.days,
                    "instr": item.instructions,
                    "order": order,
                },
            )
    if visit.addendum:
        author, body = visit.addendum
        await session.execute(
            text(
                "insert into public.consultation_addenda (id, clinic_id, consultation_id, "
                "author_name, text, created_at) values (:id, :clinic, :consultation, :author, "
                ":body, :at)"
            ),
            {
                "id": sid("addendum", visit.key),
                "clinic": CLINIC,
                "consultation": consultation_id,
                "author": author,
                "body": body,
                "at": starts + timedelta(days=8),
            },
        )
    # Finalize last, as the app does (finalized consultations reject new prescription items).
    await session.execute(
        text(
            "update public.consultations set status = 'finalized', finalized_at = :done "
            "where id = :id"
        ),
        {"id": consultation_id, "done": starts + timedelta(minutes=14)},
    )
    return consultation_id


async def seed_profile(session: AsyncSession, records: PatientRecords) -> bool:
    found = await session.scalar(
        text("select 1 from public.patient_medical_profiles where patient_id = :p"),
        {"p": records.patient},
    )
    if found:
        return False
    await session.execute(
        text(
            "insert into public.patient_medical_profiles (patient_id, clinic_id, blood_group, "
            "allergies, chronic_conditions) values (:p, :clinic, :bg, :allergies, :conditions)"
        ),
        {
            "p": records.patient,
            "clinic": CLINIC,
            "bg": records.blood_group,
            "allergies": list(records.allergies),
            "conditions": list(records.conditions),
        },
    )
    return True


async def seed_report(
    session: AsyncSession, records: PatientRecords, report: Report, patient_name: str
) -> uuid.UUID | None:
    report_id = sid("report", report.key)
    if await _exists(session, "patient_reports", report_id):
        return None
    data = lab_pdf(report, patient_name)
    path = report_path(CLINIC, records.patient, report_id, "application/pdf")
    storage = get_report_storage()
    try:
        await to_thread.run_sync(storage.upload, path, data, "application/pdf")
    except Exception as exc:
        if "exists" not in str(exc).lower() and "duplicate" not in str(exc).lower():
            raise
    await session.execute(
        text(
            "insert into public.patient_reports (id, clinic_id, patient_id, consultation_id, "
            "title, report_type, report_date, storage_path, mime_type, size_bytes) values "
            "(:id, :clinic, :patient, :consultation, :title, cast(:kind as public.report_type), "
            ":day, :path, 'application/pdf', :size)"
        ),
        {
            "id": report_id,
            "clinic": CLINIC,
            "patient": records.patient,
            "consultation": sid("consultation", report.visit_key) if report.visit_key else None,
            "title": report.title,
            "kind": report.report_type,
            "day": report.day,
            "path": path,
            "size": len(data),
        },
    )
    return report_id


async def main() -> None:
    sessionmaker = get_sessionmaker()
    created = {"visits": 0, "profiles": 0, "reports": 0}
    async with sessionmaker() as session:
        for records in RECORDS:
            name = await session.scalar(
                text("select full_name from public.patients where id = :p and clinic_id = :c"),
                {"p": records.patient, "c": CLINIC},
            )
            if name is None:
                print(f"skipped {records.patient}: not a seed patient (run supabase/seed.sql)")
                continue
            # Tokens per doctor per day (these past days have no other appointments).
            tokens: dict[tuple[uuid.UUID, date], int] = {}
            for visit in records.visits:
                key = (visit.doctor, visit.day)
                tokens[key] = tokens.get(key, 0) + 1
                consultation = await seed_visit(session, records.patient, visit, 90 + tokens[key])
                if consultation is not None:
                    created["visits"] += 1
                    await enqueue(
                        session,
                        CLINIC,
                        records.patient,
                        RecordSourceType.CONSULTATION,
                        consultation,
                    )
            if await seed_profile(session, records):
                created["profiles"] += 1
                await enqueue(
                    session, CLINIC, records.patient, RecordSourceType.PROFILE, records.patient
                )
            for report in records.reports:
                report_id = await seed_report(session, records, report, str(name))
                if report_id is not None:
                    created["reports"] += 1
                    await enqueue(
                        session, CLINIC, records.patient, RecordSourceType.REPORT, report_id
                    )
            await session.commit()
            print(f"seeded {name}")
    print(f"created {created}")

    try:
        deps = default_deps()
    except ProviderNotConfiguredError as exc:
        print(f"not indexed yet ({exc}); the API's worker or scripts.reindex will index later")
    else:
        done = await run_pending(sessionmaker, deps, clinic_id=CLINIC)
        print(f"indexed {done} sources with embedding model {deps.model}")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
