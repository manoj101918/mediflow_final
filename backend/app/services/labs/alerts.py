"""Critical-value alerts and "Mark reviewed" for the ordering doctor.

An alert is created for every critical result at release (and for new critical values in an
amendment). It stays open until the doctor it belongs to acknowledges it (one click and an
optional note), which is logged as a lab order event.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LabCriticalAlert, LabOrder, LabResult, Patient
from app.services.booking.actor import StaffActor
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success
from app.services.booking.timeutil import utcnow
from app.services.labs.common import ORDER_NOT_FOUND, add_event, load_order
from app.services.records.access import clinician_check


@dataclass(frozen=True)
class AlertView:
    alert: LabCriticalAlert
    result: LabResult
    patient_name: str
    order_number: str


async def open_alerts(session: AsyncSession, actor: StaffActor) -> BookingResult[list[AlertView]]:
    check = clinician_check(actor)
    if not check.ok:
        return failure(check.code or BookingErrorCode.FORBIDDEN, check.message)
    rows = await session.execute(
        select(LabCriticalAlert, LabResult, Patient.full_name, LabOrder.order_number)
        .join(LabResult, LabResult.id == LabCriticalAlert.result_id)
        .join(Patient, Patient.id == LabCriticalAlert.patient_id)
        .join(LabOrder, LabOrder.id == LabCriticalAlert.order_id)
        .where(
            LabCriticalAlert.clinic_id == actor.clinic_id,
            LabCriticalAlert.doctor_id == actor.doctor_id,
            LabCriticalAlert.acknowledged_at.is_(None),
        )
        .order_by(LabCriticalAlert.created_at)
    )
    return success([AlertView(a, r, name, number) for a, r, name, number in rows])


async def acknowledge(
    session: AsyncSession, actor: StaffActor, alert_id: UUID, note: str | None
) -> BookingResult[LabCriticalAlert]:
    check = clinician_check(actor)
    if not check.ok:
        return failure(check.code or BookingErrorCode.FORBIDDEN, check.message)
    alert = await session.scalar(
        select(LabCriticalAlert)
        .where(
            LabCriticalAlert.id == alert_id,
            LabCriticalAlert.clinic_id == actor.clinic_id,
            LabCriticalAlert.doctor_id == actor.doctor_id,
        )
        .with_for_update()
    )
    if alert is None:
        await session.rollback()
        return failure(BookingErrorCode.NOT_FOUND, "Alert not found.")
    if alert.acknowledged_at is None:
        alert.acknowledged_at = utcnow()
        alert.acknowledged_by = actor.user_id
        alert.note = note
        order = await load_order(session, actor.clinic_id, alert.order_id)
        if order is not None:
            add_event(session, order, "critical_ack", actor.user_id)
    await session.commit()
    return success(alert)


@dataclass(frozen=True)
class Reviewed:
    order_id: UUID
    reviewed_at: datetime


async def mark_reviewed(
    session: AsyncSession, actor: StaffActor, order_id: UUID
) -> BookingResult[Reviewed]:
    """The ordering doctor has seen the released results (removes them from the inbox)."""
    check = clinician_check(actor)
    if not check.ok:
        return failure(check.code or BookingErrorCode.FORBIDDEN, check.message)
    order = await load_order(session, actor.clinic_id, order_id, lock=True)
    if order is None or order.ordering_doctor_id != actor.doctor_id:
        await session.rollback()
        return failure(BookingErrorCode.NOT_FOUND, ORDER_NOT_FOUND)
    if order.reviewed_at is None:
        order.reviewed_at = utcnow()
        order.reviewed_by = actor.user_id
        add_event(session, order, "reviewed", actor.user_id)
    reviewed_at = order.reviewed_at
    await session.commit()
    return success(Reviewed(order.id, reviewed_at))
