"""Read side of the lab: worklists, order detail, results, trends, inbox, status counts.

What each role sees:
- lab staff: orders of their clinic with the patient identifiers needed for testing, the
  doctor's note for the lab, and earlier results of the same parameters (delta checks);
- doctors: every order and released result of any patient in their clinic;
- reception/admin: order numbers, test names and statuses only (never values).
"""

import enum
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appointment,
    Doctor,
    LabFlag,
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
)
from app.services.booking.actor import StaffActor
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success
from app.services.booking.timeutil import day_bounds, local_date, utcnow
from app.services.labs.common import (
    ORDER_NOT_FOUND,
    clinic_settings,
    lab_check,
    load_order,
)
from app.services.labs.ranges import age_on, delta_exceeded, select_range
from app.services.records.access import clinician_check

_PRIORITY_RANK = {LabPriority.STAT: 0, LabPriority.URGENT: 1, LabPriority.ROUTINE: 2}
PENDING_STATUSES = frozenset(
    {
        LabItemStatus.ORDERED,
        LabItemStatus.SAMPLE_COLLECTED,
        LabItemStatus.SAMPLE_REJECTED,
        LabItemStatus.RESULT_ENTERED,
        LabItemStatus.VERIFIED,
    }
)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


@dataclass
class ItemView:
    item: LabOrderItem
    sample: LabSample | None
    # Current values (drafts included for lab staff; released only for doctors).
    results: list[LabResult] = field(default_factory=list)
    # Superseded versions of amended results, oldest first.
    history: list[LabResult] = field(default_factory=list)


@dataclass
class OrderView:
    order: LabOrder
    patient: Patient
    doctor_name: str
    items: list[ItemView]
    samples: list[LabSample]
    report_id: UUID | None


@dataclass(frozen=True)
class PreviousValue:
    value_numeric: Decimal | None
    value_text: str | None
    unit: str | None
    flag: LabFlag | None
    released_at: datetime
    order_number: str


@dataclass
class ParameterView:
    parameter: LabTestParameter
    reference: LabReferenceRange | None
    previous: PreviousValue | None
    # The saved draft differs from `previous` by more than the parameter's delta limit.
    delta_warning: bool


@dataclass
class LabItemDetail:
    view: ItemView
    test: LabTest
    parameters: list[ParameterView]


@dataclass
class LabOrderDetail:
    order: OrderView
    items: list[LabItemDetail]
    age: int | None
    requires_verification: bool


async def _doctor_names(session: AsyncSession, ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    rows = await session.execute(select(Doctor.id, Doctor.full_name).where(Doctor.id.in_(ids)))
    return {doctor_id: name for doctor_id, name in rows}


async def _order_views(
    session: AsyncSession, orders: Sequence[LabOrder], *, released_values_only: bool
) -> list[OrderView]:
    if not orders:
        return []
    order_ids = [o.id for o in orders]
    patients = {
        p.id: p
        for p in (
            await session.scalars(
                select(Patient).where(Patient.id.in_({o.patient_id for o in orders}))
            )
        ).all()
    }
    doctors = await _doctor_names(session, {o.ordering_doctor_id for o in orders})
    items = (
        await session.scalars(
            select(LabOrderItem)
            .where(LabOrderItem.order_id.in_(order_ids))
            .order_by(LabOrderItem.sort_order, LabOrderItem.test_name)
        )
    ).all()
    samples = (
        await session.scalars(
            select(LabSample)
            .where(LabSample.order_id.in_(order_ids))
            .order_by(LabSample.collected_at)
        )
    ).all()
    sample_by_id = {s.id: s for s in samples}
    visible = [
        i.id for i in items if not released_values_only or i.status == LabItemStatus.RELEASED
    ]
    results = (
        (
            await session.scalars(
                select(LabResult)
                .where(LabResult.order_item_id.in_(visible))
                .order_by(LabResult.sort_order, LabResult.parameter_name, LabResult.version)
            )
        ).all()
        if visible
        else []
    )
    reports = await session.execute(
        select(PatientReport.lab_order_id, PatientReport.id).where(
            PatientReport.lab_order_id.in_(order_ids), PatientReport.is_generated
        )
    )
    report_by_order = {order_id: report_id for order_id, report_id in reports}

    views: dict[UUID, ItemView] = {
        i.id: ItemView(i, sample_by_id.get(i.sample_id) if i.sample_id else None) for i in items
    }
    for r in results:
        view = views[r.order_item_id]
        (view.results if r.is_current else view.history).append(r)
    by_order: dict[UUID, list[ItemView]] = {}
    for i in items:
        by_order.setdefault(i.order_id, []).append(views[i.id])
    return [
        OrderView(
            order=o,
            patient=patients[o.patient_id],
            doctor_name=doctors.get(o.ordering_doctor_id, ""),
            items=by_order.get(o.id, []),
            samples=[s for s in samples if s.order_id == o.id],
            report_id=report_by_order.get(o.id),
        )
        for o in orders
    ]


# ---------------------------------------------------------------------------
# Lab staff
# ---------------------------------------------------------------------------


class WorklistTab(enum.StrEnum):
    TO_COLLECT = "to_collect"
    IN_PROGRESS = "in_progress"
    AWAITING_VERIFICATION = "awaiting_verification"
    RELEASED_TODAY = "released_today"
    REJECTED = "rejected"


@dataclass
class WorklistRow:
    order: LabOrder
    patient: Patient
    doctor_name: str
    counts: dict[LabItemStatus, int]
    tests: list[str]
    sample_codes: list[str]


def _search(query: Select[LabOrder], q: str | None) -> Select[LabOrder]:
    text = (q or "").strip()
    if not text:
        return query
    like = f"%{text}%"
    digits = "".join(ch for ch in text if ch.isdigit())
    conditions = [
        Patient.full_name.ilike(like),
        LabOrder.order_number.ilike(like),
        LabOrder.id.in_(select(LabSample.order_id).where(LabSample.sample_code.ilike(like))),
    ]
    if len(digits) >= 4:
        conditions.append(Patient.phone.like(f"%{digits}%"))
    return query.where(or_(*conditions))


async def worklist(
    session: AsyncSession, actor: StaffActor, tab: WorklistTab, q: str | None = None
) -> BookingResult[list[WorklistRow]]:
    checked = lab_check(actor)
    if not checked.ok:
        return failure(checked.code or BookingErrorCode.FORBIDDEN, checked.message)
    settings = await clinic_settings(session, actor.clinic_id)

    item_filter = {
        WorklistTab.TO_COLLECT: LabOrderItem.status == LabItemStatus.ORDERED,
        WorklistTab.IN_PROGRESS: LabOrderItem.status == LabItemStatus.SAMPLE_COLLECTED,
        WorklistTab.AWAITING_VERIFICATION: LabOrderItem.status.in_(
            [LabItemStatus.RESULT_ENTERED, LabItemStatus.VERIFIED]
        ),
        WorklistTab.REJECTED: LabOrderItem.status == LabItemStatus.SAMPLE_REJECTED,
    }
    if tab == WorklistTab.RELEASED_TODAY:
        start, end = day_bounds(local_date(utcnow(), settings.tz), settings.tz)
        condition = and_(
            LabOrderItem.status == LabItemStatus.RELEASED,
            LabOrderItem.released_at >= start,
            LabOrderItem.released_at < end,
        )
    else:
        condition = item_filter[tab]
    # With verification off, submitted results wait for release under "In progress".
    if tab == WorklistTab.IN_PROGRESS and not settings.requires_verification:
        condition = LabOrderItem.status.in_(
            [LabItemStatus.SAMPLE_COLLECTED, LabItemStatus.RESULT_ENTERED]
        )

    query = (
        select(LabOrder)
        .join(Patient, Patient.id == LabOrder.patient_id)
        .where(
            LabOrder.clinic_id == actor.clinic_id,
            LabOrder.id.in_(select(LabOrderItem.order_id).where(condition)),
        )
    )
    orders = list((await session.scalars(_search(query, q).limit(200))).all())
    views = await _order_views(session, orders, released_values_only=True)
    rows = [
        WorklistRow(
            order=v.order,
            patient=v.patient,
            doctor_name=v.doctor_name,
            counts=dict(Counter(i.item.status for i in v.items)),
            tests=[i.item.test_name for i in v.items if i.item.status != LabItemStatus.CANCELLED],
            sample_codes=[s.sample_code for s in v.samples if s.rejected_at is None],
        )
        for v in views
    ]
    newest_first = tab == WorklistTab.RELEASED_TODAY
    rows.sort(
        key=lambda r: (
            _PRIORITY_RANK[r.order.priority],
            -r.order.created_at.timestamp() if newest_first else r.order.created_at.timestamp(),
        )
    )
    return success(rows)


async def _previous_values(
    session: AsyncSession, patient_id: UUID, order_id: UUID, codes: set[str]
) -> dict[str, PreviousValue]:
    """Latest released value per parameter code from the patient's other orders."""
    if not codes:
        return {}
    rows = await session.execute(
        select(LabResult, LabOrderItem.released_at, LabOrder.order_number)
        .join(LabOrderItem, LabOrderItem.id == LabResult.order_item_id)
        .join(LabOrder, LabOrder.id == LabOrderItem.order_id)
        .where(
            LabOrder.patient_id == patient_id,
            LabOrder.id != order_id,
            LabOrderItem.status == LabItemStatus.RELEASED,
            LabResult.is_current,
            LabResult.parameter_code.in_(codes),
        )
        .order_by(LabOrderItem.released_at.desc())
    )
    out: dict[str, PreviousValue] = {}
    for result, released_at, number in rows:
        if result.parameter_code in out or released_at is None:
            continue
        out[result.parameter_code] = PreviousValue(
            result.value_numeric,
            result.value_text,
            result.unit,
            result.flag,
            released_at,
            number,
        )
    return out


async def lab_order_detail(
    session: AsyncSession, actor: StaffActor, order_id: UUID
) -> BookingResult[LabOrderDetail]:
    """Everything the lab needs to collect and report one order."""
    checked = lab_check(actor)
    if not checked.ok:
        return failure(checked.code or BookingErrorCode.FORBIDDEN, checked.message)
    order = await load_order(session, actor.clinic_id, order_id)
    if order is None:
        return failure(BookingErrorCode.NOT_FOUND, ORDER_NOT_FOUND)
    settings = await clinic_settings(session, actor.clinic_id)
    [view] = await _order_views(session, [order], released_values_only=False)
    patient = view.patient

    test_ids = {i.item.test_id for i in view.items}
    tests = {
        t.id: t
        for t in (await session.scalars(select(LabTest).where(LabTest.id.in_(test_ids)))).all()
    }
    params = (
        await session.scalars(
            select(LabTestParameter)
            .where(LabTestParameter.test_id.in_(test_ids))
            .order_by(LabTestParameter.sort_order, LabTestParameter.name)
        )
    ).all()
    ranges: dict[UUID, list[LabReferenceRange]] = {}
    for r in (
        await session.scalars(
            select(LabReferenceRange).where(
                LabReferenceRange.parameter_id.in_([p.id for p in params])
            )
        )
    ).all():
        ranges.setdefault(r.parameter_id, []).append(r)
    previous = await _previous_values(session, patient.id, order.id, {p.code for p in params})

    details: list[LabItemDetail] = []
    for item_view in view.items:
        collected = item_view.sample.collected_at if item_view.sample else utcnow()
        age = age_on(local_date(collected, settings.tz), patient.date_of_birth, patient.age_years)
        current = {r.parameter_id: r for r in item_view.results}
        parameter_views = []
        for p in params:
            if p.test_id != item_view.item.test_id:
                continue
            draft = current.get(p.id)
            if not p.is_active and draft is None:
                continue
            prev = previous.get(p.code)
            warning = bool(
                draft is not None
                and prev is not None
                and draft.value_numeric is not None
                and prev.value_numeric is not None
                and delta_exceeded(prev.value_numeric, draft.value_numeric, p.delta_percent)
            )
            parameter_views.append(
                ParameterView(
                    p, select_range(ranges.get(p.id, []), patient.gender, age), prev, warning
                )
            )
        details.append(LabItemDetail(item_view, tests[item_view.item.test_id], parameter_views))

    today = local_date(utcnow(), settings.tz)
    return success(
        LabOrderDetail(
            order=view,
            items=details,
            age=age_on(today, patient.date_of_birth, patient.age_years),
            requires_verification=settings.requires_verification,
        )
    )


# ---------------------------------------------------------------------------
# Doctors
# ---------------------------------------------------------------------------


async def _clinic_patient(
    session: AsyncSession, actor: StaffActor, patient_id: UUID
) -> Patient | None:
    return await session.scalar(
        select(Patient).where(Patient.id == patient_id, Patient.clinic_id == actor.clinic_id)
    )


async def patient_lab_results(
    session: AsyncSession, actor: StaffActor, patient_id: UUID
) -> BookingResult[list[OrderView]]:
    """All of a patient's orders, newest first; values of released tests only."""
    check = clinician_check(actor)
    if not check.ok:
        return failure(check.code or BookingErrorCode.FORBIDDEN, check.message)
    if await _clinic_patient(session, actor, patient_id) is None:
        return failure(BookingErrorCode.NOT_FOUND, "Patient not found.")
    orders = (
        await session.scalars(
            select(LabOrder)
            .where(LabOrder.clinic_id == actor.clinic_id, LabOrder.patient_id == patient_id)
            .order_by(LabOrder.created_at.desc())
        )
    ).all()
    return success(await _order_views(session, orders, released_values_only=True))


async def appointment_orders(
    session: AsyncSession, actor: StaffActor, appointment_id: UUID
) -> BookingResult[list[OrderView]]:
    """Orders placed during one visit (the doctor's "Order tests" panel)."""
    check = clinician_check(actor)
    if not check.ok:
        return failure(check.code or BookingErrorCode.FORBIDDEN, check.message)
    orders = (
        await session.scalars(
            select(LabOrder)
            .where(LabOrder.clinic_id == actor.clinic_id, LabOrder.appointment_id == appointment_id)
            .order_by(LabOrder.created_at)
        )
    ).all()
    return success(await _order_views(session, orders, released_values_only=True))


@dataclass(frozen=True)
class TrendPoint:
    value: Decimal
    flag: LabFlag | None
    ref_low: Decimal | None
    ref_high: Decimal | None
    unit: str | None
    released_at: datetime
    order_id: UUID
    order_item_id: UUID
    order_number: str


@dataclass
class TrendSeries:
    code: str
    name: str
    unit: str | None
    points: list[TrendPoint]


async def lab_trends(
    session: AsyncSession, actor: StaffActor, patient_id: UUID
) -> BookingResult[list[TrendSeries]]:
    """Released numeric values per parameter code, oldest first (for the Lab trends tab)."""
    check = clinician_check(actor)
    if not check.ok:
        return failure(check.code or BookingErrorCode.FORBIDDEN, check.message)
    if await _clinic_patient(session, actor, patient_id) is None:
        return failure(BookingErrorCode.NOT_FOUND, "Patient not found.")
    rows = await session.execute(
        select(LabResult, LabOrderItem.released_at, LabOrder.id, LabOrder.order_number)
        .join(LabOrderItem, LabOrderItem.id == LabResult.order_item_id)
        .join(LabOrder, LabOrder.id == LabOrderItem.order_id)
        .where(
            LabOrder.clinic_id == actor.clinic_id,
            LabOrder.patient_id == patient_id,
            LabOrderItem.status == LabItemStatus.RELEASED,
            LabResult.is_current,
            LabResult.value_numeric.is_not(None),
        )
        .order_by(LabOrderItem.released_at)
    )
    series: dict[str, TrendSeries] = {}
    for result, released_at, order_id, number in rows:
        if released_at is None or result.value_numeric is None:
            continue
        s = series.setdefault(
            result.parameter_code,
            TrendSeries(result.parameter_code, result.parameter_name, result.unit, []),
        )
        s.points.append(
            TrendPoint(
                result.value_numeric,
                result.flag,
                result.ref_low,
                result.ref_high,
                result.unit,
                released_at,
                order_id,
                result.order_item_id,
                number,
            )
        )
    return success(sorted(series.values(), key=lambda s: (-len(s.points), s.name)))


@dataclass
class InboxRow:
    view: OrderView
    abnormal: int
    critical: int


async def results_inbox(session: AsyncSession, actor: StaffActor) -> BookingResult[list[InboxRow]]:
    """Released results of the doctor's own orders that they have not marked reviewed."""
    check = clinician_check(actor)
    if not check.ok:
        return failure(check.code or BookingErrorCode.FORBIDDEN, check.message)
    orders = (
        await session.scalars(
            select(LabOrder)
            .where(
                LabOrder.clinic_id == actor.clinic_id,
                LabOrder.ordering_doctor_id == actor.doctor_id,
                LabOrder.status.in_([LabOrderStatus.RELEASED, LabOrderStatus.PARTIALLY_RELEASED]),
                LabOrder.reviewed_at.is_(None),
            )
            .order_by(LabOrder.updated_at.desc())
            .limit(100)
        )
    ).all()
    views = await _order_views(session, orders, released_values_only=True)
    rows = []
    for v in views:
        flags = [r.flag for i in v.items for r in i.results if r.flag]
        rows.append(
            InboxRow(
                v,
                abnormal=sum(1 for f in flags if f.value != "normal"),
                critical=sum(1 for f in flags if f.value.startswith("critical")),
            )
        )
    return success(rows)


@dataclass(frozen=True)
class StatusCounts:
    pending: int = 0
    ready: int = 0


async def status_summary(
    session: AsyncSession, actor: StaffActor, day: date
) -> dict[UUID, StatusCounts]:
    """Per appointment on `day`: tests still pending and tests released (no values)."""
    rows = await session.execute(
        select(LabOrder.appointment_id, LabOrderItem.status, func.count())
        .join(LabOrderItem, LabOrderItem.order_id == LabOrder.id)
        .join(Appointment, Appointment.id == LabOrder.appointment_id)
        .where(
            LabOrder.clinic_id == actor.clinic_id,
            Appointment.appointment_date == day,
        )
        .group_by(LabOrder.appointment_id, LabOrderItem.status)
    )
    pending: Counter[UUID] = Counter()
    ready: Counter[UUID] = Counter()
    for appointment_id, status, count in rows:
        if status == LabItemStatus.RELEASED:
            ready[appointment_id] += count
        elif status in PENDING_STATUSES:
            pending[appointment_id] += count
    return {a: StatusCounts(pending[a], ready[a]) for a in set(pending) | set(ready)}


async def patient_order_statuses(
    session: AsyncSession, actor: StaffActor, patient_id: UUID
) -> BookingResult[list[OrderView]]:
    """Front desk: a patient's orders (numbers, tests, statuses). Never values."""
    if await _clinic_patient(session, actor, patient_id) is None:
        return failure(BookingErrorCode.NOT_FOUND, "Patient not found.")
    orders = (
        await session.scalars(
            select(LabOrder)
            .where(LabOrder.clinic_id == actor.clinic_id, LabOrder.patient_id == patient_id)
            .order_by(LabOrder.created_at.desc())
            .limit(50)
        )
    ).all()
    views = await _order_views(session, orders, released_values_only=True)
    for v in views:
        for i in v.items:
            i.results = []
            i.history = []
    return success(views)


async def order_view(
    session: AsyncSession, clinic_id: UUID, order_id: UUID, *, released_values_only: bool
) -> OrderView | None:
    order = await load_order(session, clinic_id, order_id)
    if order is None:
        return None
    [view] = await _order_views(session, [order], released_values_only=released_values_only)
    return view
