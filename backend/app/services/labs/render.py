"""Released lab results as text for the chatbot's index (source_type 'lab_result').

One piece per released test, so a citation points at the right test of the order:
"Lab result, 02 Oct 2026, order LAB-20261002-0007, ordered by Dr. Sharma. HbA1c: HbA1c 6.9 %
(reference 4.0 - 5.6) HIGH." Only current versions are rendered; amended ones say so.
"""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Clinic,
    Doctor,
    LabCriticalAlert,
    LabFlag,
    LabItemStatus,
    LabOrder,
    LabOrderItem,
    LabResult,
)
from app.services.booking.timeutil import clinic_tz, local_date
from app.services.ingestion.render import Piece, RenderedSource, human_date
from app.services.labs.ranges import format_number

FLAG_TEXT = {
    LabFlag.LOW: "LOW",
    LabFlag.HIGH: "HIGH",
    LabFlag.CRITICAL_LOW: "CRITICAL LOW",
    LabFlag.CRITICAL_HIGH: "CRITICAL HIGH",
    LabFlag.ABNORMAL: "ABNORMAL",
}


def describe_result(r: LabResult) -> str:
    value = format_number(r.value_numeric) if r.value_numeric is not None else r.value_text or ""
    text = f"{r.parameter_name} {value}"
    if r.unit:
        text += f" {r.unit}"
    if r.range_label:
        text += f" (reference {r.range_label})"
    flag = FLAG_TEXT.get(r.flag) if r.flag else None
    if flag:
        text += f" {flag}"
    if r.version > 1:
        text += f" [amended: {r.amended_reason}]"
    return text


async def released_results(
    session: AsyncSession, order_id: UUID
) -> list[tuple[LabOrderItem, list[LabResult]]]:
    items = (
        await session.scalars(
            select(LabOrderItem)
            .where(LabOrderItem.order_id == order_id, LabOrderItem.status == LabItemStatus.RELEASED)
            .order_by(LabOrderItem.sort_order, LabOrderItem.test_name)
        )
    ).all()
    if not items:
        return []
    results = (
        await session.scalars(
            select(LabResult)
            .where(LabResult.order_item_id.in_([i.id for i in items]), LabResult.is_current)
            .order_by(LabResult.sort_order, LabResult.parameter_name)
        )
    ).all()
    by_item: dict[UUID, list[LabResult]] = {}
    for r in results:
        by_item.setdefault(r.order_item_id, []).append(r)
    return [(i, by_item.get(i.id, [])) for i in items]


async def render_lab_order(session: AsyncSession, order_id: UUID) -> RenderedSource | None:
    """The order's released results, or None when nothing is released (yet)."""
    order = await session.get(LabOrder, order_id)
    if order is None:
        return None
    released = await released_results(session, order_id)
    if not released:
        return None
    clinic = await session.get(Clinic, order.clinic_id)
    tz = clinic_tz(clinic.timezone if clinic else "Asia/Kolkata")
    doctor = await session.scalar(
        select(Doctor.full_name).where(Doctor.id == order.ordering_doctor_id)
    )
    pieces = []
    latest: date | None = None
    for item, results in released:
        if item.released_at is None or not results:
            continue
        day = local_date(item.released_at, tz)
        latest = max(latest, day) if latest else day
        heading = f"Lab result, {human_date(day)}, order {order.order_number}"
        if doctor:
            heading += f", ordered by {doctor}"
        body = "; ".join(describe_result(r) for r in results)
        pieces.append(
            Piece(
                f"{heading}. {item.test_name}: {body}.",
                {
                    "order_item_id": str(item.id),
                    "order_number": order.order_number,
                    "test_code": item.test_code,
                    "date": day.isoformat(),
                },
            )
        )
    if not pieces:
        return None
    return RenderedSource(
        clinic_id=order.clinic_id,
        patient_id=order.patient_id,
        source_date=latest,
        heading=f"Lab results, order {order.order_number}",
        pieces=pieces,
    )


async def lab_summary_lines(session: AsyncSession, patient_id: UUID, today: date) -> list[str]:
    """For the chatbot's patient summary: the latest abnormal released value per parameter
    (last 12 months) and critical results nobody has acknowledged yet."""
    since = today - timedelta(days=365)
    rows = await session.execute(
        select(LabResult, LabOrderItem.released_at, LabOrder.order_number)
        .join(LabOrderItem, LabOrderItem.id == LabResult.order_item_id)
        .join(LabOrder, LabOrder.id == LabOrderItem.order_id)
        .where(
            LabOrder.patient_id == patient_id,
            LabOrderItem.status == LabItemStatus.RELEASED,
            LabResult.is_current,
            LabOrderItem.released_at >= datetime.combine(since, time(), tzinfo=UTC),
        )
        .order_by(LabOrderItem.released_at.desc())
    )
    latest: dict[str, tuple[LabResult, datetime, str]] = {}
    for result, released_at, number in rows:
        if released_at is not None and result.parameter_code not in latest:
            latest[result.parameter_code] = (result, released_at, number)
    abnormal = [
        f"- {describe_result(r)} on {human_date(at.date())} ({number})"
        for r, at, number in latest.values()
        if r.flag is not None and r.flag != LabFlag.NORMAL
    ]
    lines = []
    if abnormal:
        lines.append("Latest abnormal lab values (last 12 months, most recent per test):")
        lines.extend(abnormal[:15])
    open_alerts = await session.scalar(
        select(func.count())
        .select_from(LabCriticalAlert)
        .where(
            LabCriticalAlert.patient_id == patient_id, LabCriticalAlert.acknowledged_at.is_(None)
        )
    )
    if open_alerts:
        lines.append(f"Unacknowledged critical lab results: {open_alerts}.")
    return lines
