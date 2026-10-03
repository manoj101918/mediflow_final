"""Seed the in-house lab for the seed clinic (dev only, synthetic data).

Run after supabase/seed.sql, scripts.seed_users and scripts.seed_clinical:

    cd backend
    uv run python -m scripts.seed_lab
    uv run python -m scripts.reindex --all     # index the backfilled results (Voyage 3 RPM)

What it adds (idempotent: fixed ids, existing rows are kept):
- the starter test catalog (plus paediatric CBC ranges for clinics seeded before they existed);
- released lab orders with structured results for every seed lab PDF, on the PDF's date and
  with its values. Each PDF is linked to its order as the lab's own PDF (an UPDATE of
  patient_reports.lab_order_id; nothing is deleted) and its old 'report' chunks are dropped,
  so the chatbot sees each value once, from the structured results;
- a few open orders for the lab worklist (to collect, in progress, awaiting verification)
  and one released critical potassium with an unacknowledged alert.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appointment,
    LabCriticalAlert,
    LabItemStatus,
    LabOrder,
    LabOrderItem,
    LabOrderStatus,
    LabPriority,
    LabReferenceRange,
    LabResult,
    LabSample,
    LabTest,
    LabTestParameter,
    Patient,
    PatientReport,
    Profile,
    RecordSourceType,
    UserRole,
)
from app.db.session import dispose_engine, get_sessionmaker
from app.services.booking.timeutil import clinic_tz, today_local, utcnow
from app.services.ingestion.indexer import remove_source
from app.services.ingestion.jobs import enqueue
from app.services.labs.catalog_seed import CATALOG, install_catalog
from app.services.labs.numbers import next_order_number, next_sample_code
from app.services.labs.ranges import CRITICAL_FLAGS, age_on, select_range
from app.services.labs.transitions import derive_order_status
from app.services.labs.workflow import ComputedValue, parse_value, snapshot_result

CLINIC = UUID("11111111-1111-4111-8111-111111111111")
NAMESPACE = uuid.UUID("6f1d0c9e-5b0a-4c4e-9a43-6d0a2c1f0b77")  # same as seed_clinical
LAB_NAMESPACE = uuid.UUID("2b7f3c1e-8d4a-4f6b-9c2e-5a1d7e3f9b40")

PRAKASH = UUID("2037da99-bae2-d71e-a051-2f8a85bb826f")
RAVI = UUID("b8504f2a-013a-51ed-87ef-03c526cf5e0d")
LAKSHMI = UUID("0fbffa1b-5745-34d3-4fa6-e71008cab14b")
RAJESH = UUID("000c60fd-f4af-106f-94d3-39c270e1a34a")
ANANYA = UUID("3a2d238e-2ae8-1a5a-44ca-d67fc14cdbdb")


def sid(*parts: object) -> UUID:
    return uuid.uuid5(NAMESPACE, "/".join(str(p) for p in parts))


def lid(*parts: object) -> UUID:
    return uuid.uuid5(LAB_NAMESPACE, "/".join(str(p) for p in parts))


@dataclass(frozen=True)
class SeedOrder:
    key: str
    patient: UUID
    visit_key: str  # seed_clinical visit whose appointment placed the order
    day: date | None  # None = today
    # test code -> {parameter code: value}
    tests: dict[str, dict[str, str]]
    final: LabItemStatus = LabItemStatus.RELEASED
    report_key: str | None = None  # seed_clinical report (PDF) this order backs
    priority: LabPriority = LabPriority.ROUTINE
    note: str | None = None


ORDERS: tuple[SeedOrder, ...] = (
    # Backfill of the seed lab PDFs (same dates and values).
    SeedOrder(
        "prakash-1",
        PRAKASH,
        "prakash-1",
        date(2025, 12, 6),
        {
            "HBA1C": {"HBA1C": "8.1"},
            "FBS": {"FBS": "168"},
            "PPBS": {"PPBS": "246"},
            "KFT": {"CREAT": "0.9"},
        },
        report_key="prakash-lab-1",
        note="New patient, polyuria and thirst",
    ),
    SeedOrder(
        "prakash-2",
        PRAKASH,
        "prakash-2",
        date(2026, 3, 10),
        {"HBA1C": {"HBA1C": "7.4"}, "FBS": {"FBS": "138"}},
        report_key="prakash-lab-2",
        note="Diabetic, on metformin",
    ),
    SeedOrder(
        "prakash-3",
        PRAKASH,
        "prakash-4",
        date(2026, 9, 12),
        {
            "HBA1C": {"HBA1C": "6.9"},
            "FBS": {"FBS": "112"},
            "LIPID": {"CHOL": "186", "LDL": "118", "HDL": "42", "TG": "160"},
            "UMALB": {"UMALB": "18"},
        },
        report_key="prakash-lab-3",
        note="Diabetic on metformin + glimepiride, hypertensive",
    ),
    SeedOrder(
        "lakshmi-1",
        LAKSHMI,
        "lakshmi-1",
        date(2026, 1, 31),
        {"TSH": {"TSH": "8.2"}},
        note="Hypothyroid on levothyroxine",
    ),
    SeedOrder(
        "lakshmi-2",
        LAKSHMI,
        "lakshmi-2",
        date(2026, 4, 4),
        {"TSH": {"TSH": "3.1"}},
        report_key="lakshmi-thyroid",
        note="Levothyroxine dose increased in Feb",
    ),
    SeedOrder(
        "rajesh-1",
        RAJESH,
        "rajesh-2",
        date(2026, 2, 14),
        {"LIPID": {"CHOL": "238", "LDL": "162", "HDL": "38", "TG": "210"}},
        report_key="rajesh-lipid",
    ),
    SeedOrder(
        "ananya-1",
        ANANYA,
        "ananya-2",
        date(2026, 5, 3),
        {"CBC": {"HB": "12.1", "TLC": "11.8", "PLT": "260"}},
        report_key="ananya-cbc",
    ),
    # Open work for the lab worklist (today).
    SeedOrder(
        "ravi-open",
        RAVI,
        "ravi-3",
        None,
        {"CBC": {}, "ESR": {}},
        final=LabItemStatus.ORDERED,
        priority=LabPriority.STAT,
        note="Fever 3 days, rule out infection",
    ),
    SeedOrder(
        "rajesh-open",
        RAJESH,
        "rajesh-3",
        None,
        {"KFT": {}},
        final=LabItemStatus.SAMPLE_COLLECTED,
        priority=LabPriority.URGENT,
    ),
    SeedOrder(
        "lakshmi-open",
        LAKSHMI,
        "lakshmi-3",
        None,
        {"VITD": {"VITD": "18"}, "B12": {"B12": "190"}},
        final=LabItemStatus.RESULT_ENTERED,
        note="Fatigue, on PPI",
    ),
    # A critical value the ordering doctor still has to acknowledge.
    SeedOrder(
        "rajesh-critical",
        RAJESH,
        "rajesh-3",
        None,
        {"ELEC": {"NA": "134", "K": "6.4", "CL": "101"}},
        priority=LabPriority.URGENT,
        note="On telmisartan + spironolactone",
    ),
)

PAEDIATRIC = {
    # (test, parameter) -> (low, high, critical_low, critical_high) for ages 1-12
    ("CBC", "HB"): ("11.5", "15.5", "7.0", "20.0"),
    ("CBC", "TLC"): ("4.5", "13.5", "2.0", "30.0"),
    ("CBC", "PLT"): ("150", "450", "20", "1000"),
}


async def _add_paediatric_ranges(session: AsyncSession) -> int:
    """Clinics seeded before the paediatric CBC bands existed get them (never duplicated)."""
    added = 0
    for (test_code, code), (low, high, clow, chigh) in PAEDIATRIC.items():
        param = await session.scalar(
            select(LabTestParameter)
            .join(LabTest, LabTest.id == LabTestParameter.test_id)
            .where(
                LabTest.clinic_id == CLINIC,
                LabTest.code == test_code,
                LabTestParameter.code == code,
            )
        )
        if param is None:
            continue
        banded = await session.scalar(
            select(LabReferenceRange.id).where(
                LabReferenceRange.parameter_id == param.id,
                LabReferenceRange.age_max_years.is_not(None),
            )
        )
        if banded is None:
            session.add(
                LabReferenceRange(
                    parameter_id=param.id,
                    age_min_years=1,
                    age_max_years=12,
                    low=Decimal(low),
                    high=Decimal(high),
                    critical_low=Decimal(clow),
                    critical_high=Decimal(chigh),
                )
            )
            added += 1
    await session.commit()
    return added


async def _add_results(
    session: AsyncSession,
    spec: SeedOrder,
    item: LabOrderItem,
    values: dict[str, str],
    patient: Patient,
    age: int | None,
    staff: dict[UserRole, UUID],
    done_at: datetime,
) -> None:
    order_id = item.order_id
    test_code = item.test_code
    appointment = await session.get(Appointment, sid("appt", spec.visit_key))
    assert appointment is not None  # noqa: S101 - checked by the caller
    params = {
        p.code: p
        for p in (
            await session.scalars(
                select(LabTestParameter).where(LabTestParameter.test_id == item.test_id)
            )
        ).all()
    }
    for code, raw in values.items():
        param = params[code]
        ranges = (
            await session.scalars(
                select(LabReferenceRange).where(LabReferenceRange.parameter_id == param.id)
            )
        ).all()
        result = LabResult(
            id=lid("result", spec.key, test_code, code),
            order_item_id=item.id,
            parameter_id=param.id,
            entered_by=staff[UserRole.LAB_TECHNICIAN],
            entered_at=done_at,
        )
        snapshot_result(
            result,
            ComputedValue(
                param,
                *parse_value(param, raw),
                select_range(ranges, patient.gender, age),
            ),
        )
        session.add(result)
        await session.flush()
        if spec.final == LabItemStatus.RELEASED and result.flag in CRITICAL_FLAGS:
            session.add(
                LabCriticalAlert(
                    clinic_id=CLINIC,
                    result_id=result.id,
                    order_id=order_id,
                    patient_id=spec.patient,
                    doctor_id=appointment.doctor_id,
                    created_at=done_at,
                )
            )


async def _seed_order(
    session: AsyncSession, spec: SeedOrder, tests: dict[str, LabTest], staff: dict[UserRole, UUID]
) -> str:
    order_id = lid("order", spec.key)
    if await session.get(LabOrder, order_id) is not None:
        return "exists"
    appointment = await session.get(Appointment, sid("appt", spec.visit_key))
    patient = await session.get(Patient, spec.patient)
    if appointment is None or patient is None:
        return "missing seed_clinical data"
    tz = clinic_tz()
    day = spec.day or today_local(tz)
    # Backfilled orders: 09:00 on their day; today's open work: placed two hours ago.
    if spec.day:
        ordered_at = datetime.combine(day, time(9, 0), tzinfo=tz)
    else:
        ordered_at = utcnow() - timedelta(hours=2)
    done_at = ordered_at + timedelta(hours=1)
    number = await next_order_number(session, CLINIC, day)
    consultation = (
        await session.scalar(
            select(PatientReport.consultation_id).where(
                PatientReport.id == sid("report", spec.report_key)
            )
        )
        if spec.report_key
        else None
    )
    order = LabOrder(
        id=order_id,
        clinic_id=CLINIC,
        patient_id=spec.patient,
        ordering_doctor_id=appointment.doctor_id,
        appointment_id=appointment.id,
        consultation_id=consultation or (sid("consultation", spec.visit_key)),
        order_number=number,
        priority=spec.priority,
        clinical_note=spec.note,
        created_at=ordered_at,
        updated_at=done_at,
        reviewed_at=done_at if spec.day else None,
    )
    session.add(order)
    await session.flush()

    collected = spec.final != LabItemStatus.ORDERED
    sample_id: UUID | None = None
    if collected:
        sample = LabSample(
            id=lid("sample", spec.key),
            clinic_id=CLINIC,
            order_id=order_id,
            sample_code=await next_sample_code(session, CLINIC, day),
            sample_type=tests[next(iter(spec.tests))].sample_type,
            container=tests[next(iter(spec.tests))].container,
            collected_by=staff[UserRole.LAB_TECHNICIAN],
            collected_at=ordered_at + timedelta(minutes=20),
        )
        session.add(sample)
        await session.flush()
        sample_id = sample.id

    age = age_on(day, patient.date_of_birth, patient.age_years)
    statuses = []
    for position, (test_code, values) in enumerate(spec.tests.items()):
        test = tests[test_code]
        item = LabOrderItem(
            id=lid("item", spec.key, test_code),
            order_id=order_id,
            test_id=test.id,
            test_code=test.code,
            test_name=test.name,
            status=spec.final,
            sort_order=position,
            sample_id=sample_id,
        )
        if spec.final in (LabItemStatus.RESULT_ENTERED, LabItemStatus.RELEASED):
            item.entered_by, item.entered_at = staff[UserRole.LAB_TECHNICIAN], done_at
        if spec.final == LabItemStatus.RELEASED:
            item.verified_by, item.verified_at = staff[UserRole.LAB_SUPERVISOR], done_at
            item.released_by, item.released_at = staff[UserRole.LAB_SUPERVISOR], done_at
        session.add(item)
        await session.flush()
        statuses.append(item.status)
        await _add_results(session, spec, item, values, patient, age, staff, done_at)
    order.status = derive_order_status(statuses)

    if spec.report_key:
        # The seed PDF becomes this order's lab-machine PDF; its old chunks go (the structured
        # results are indexed instead, so the chatbot sees each value once).
        report_id = sid("report", spec.report_key)
        await session.execute(
            update(PatientReport).where(PatientReport.id == report_id).values(lab_order_id=order_id)
        )
        await remove_source(session, RecordSourceType.REPORT, report_id)
    if order.status in (LabOrderStatus.RELEASED, LabOrderStatus.PARTIALLY_RELEASED):
        await enqueue(session, CLINIC, spec.patient, RecordSourceType.LAB_RESULT, order_id)
    await session.commit()
    return f"{number} {order.status.value}"


async def main() -> None:
    async with get_sessionmaker()() as session:
        added = await install_catalog(session, CLINIC)
        print(f"lab catalog: {added} test(s) added")
        print(f"paediatric ranges added: {await _add_paediatric_ranges(session)}")
        tests = {
            t.code: t
            for t in (
                await session.scalars(select(LabTest).where(LabTest.clinic_id == CLINIC))
            ).all()
        }
        missing = {c.code for c in CATALOG} - set(tests)
        if missing:
            raise SystemExit(f"catalog incomplete: {sorted(missing)}")
        staff = {
            role: uid
            for role, uid in (
                await session.execute(
                    select(Profile.role, Profile.id).where(
                        Profile.clinic_id == CLINIC,
                        Profile.role.in_([UserRole.LAB_TECHNICIAN, UserRole.LAB_SUPERVISOR]),
                    )
                )
            )
        }
        if len(staff) < 2:
            raise SystemExit("Lab logins missing: run scripts.seed_users first.")
        for spec in ORDERS:
            print(f"order {spec.key}: {await _seed_order(session, spec, tests, staff)}")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
