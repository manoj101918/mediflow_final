"""Ordering and cancelling lab tests.

- A doctor orders tests only on their own appointment while it is checked in or in
  consultation (the same rule as writing the visit); other doctors' appointments are
  NOT_FOUND. The visit's draft consultation, if any, is linked.
- Tests can be cancelled only while still `ordered` (before the sample is collected), by the
  ordering doctor or by lab staff; lab staff must give a reason.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appointment,
    AppointmentStatus,
    Consultation,
    LabItemStatus,
    LabOrder,
    LabOrderItem,
    LabOrderStatus,
    LabPriority,
    LabTest,
)
from app.services.booking.actor import StaffActor
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success
from app.services.booking.timeutil import local_date, utcnow
from app.services.labs.common import (
    ORDER_NOT_FOUND,
    add_event,
    clinic_settings,
    load_order,
    move,
    order_items,
    refresh_order,
)
from app.services.labs.numbers import next_order_number
from app.services.records.access import clinician_check

ORDERABLE_STATUSES = frozenset({AppointmentStatus.CHECKED_IN, AppointmentStatus.IN_CONSULTATION})
MAX_TESTS_PER_ORDER = 30


@dataclass(frozen=True)
class NewLabOrder:
    test_ids: Sequence[UUID]
    priority: LabPriority = LabPriority.ROUTINE
    clinical_note: str | None = None


async def _own_open_appointment(
    session: AsyncSession, actor: StaffActor, appointment_id: UUID
) -> BookingResult[Appointment]:
    check = clinician_check(actor)
    if not check.ok:
        return failure(check.code or BookingErrorCode.FORBIDDEN, check.message)
    appointment = await session.scalar(
        select(Appointment).where(
            Appointment.id == appointment_id, Appointment.clinic_id == actor.clinic_id
        )
    )
    if appointment is None or appointment.doctor_id != actor.doctor_id:
        return failure(BookingErrorCode.NOT_FOUND, "Appointment not found.")
    if appointment.status not in ORDERABLE_STATUSES:
        return failure(
            BookingErrorCode.INVALID_TRANSITION,
            "Tests can only be ordered while the patient is checked in or in consultation.",
        )
    return success(appointment)


async def create_order(
    session: AsyncSession, actor: StaffActor, appointment_id: UUID, data: NewLabOrder
) -> BookingResult[LabOrder]:
    try:
        result = await _create_order(session, actor, appointment_id, data)
    except Exception:
        await session.rollback()
        raise
    if result.ok:
        await session.commit()
    else:
        await session.rollback()
    return result


async def _create_order(
    session: AsyncSession, actor: StaffActor, appointment_id: UUID, data: NewLabOrder
) -> BookingResult[LabOrder]:
    owned = await _own_open_appointment(session, actor, appointment_id)
    if not owned.ok:
        return failure(owned.code or BookingErrorCode.NOT_FOUND, owned.message)
    appointment = owned.unwrap()

    wanted = list(dict.fromkeys(data.test_ids))
    if not wanted:
        return failure(BookingErrorCode.VALIDATION, "Choose at least one test.")
    if len(wanted) > MAX_TESTS_PER_ORDER:
        return failure(BookingErrorCode.VALIDATION, "Too many tests in one order.")
    tests = {
        t.id: t
        for t in (
            await session.scalars(
                select(LabTest).where(
                    LabTest.id.in_(wanted), LabTest.clinic_id == actor.clinic_id, LabTest.is_active
                )
            )
        ).all()
    }
    if len(tests) != len(wanted):
        return failure(BookingErrorCode.VALIDATION, "One or more tests are not available.")

    consultation_id = await session.scalar(
        select(Consultation.id).where(Consultation.appointment_id == appointment.id)
    )
    settings = await clinic_settings(session, actor.clinic_id)
    number = await next_order_number(session, actor.clinic_id, local_date(utcnow(), settings.tz))
    order = LabOrder(
        clinic_id=actor.clinic_id,
        patient_id=appointment.patient_id,
        ordering_doctor_id=appointment.doctor_id,
        appointment_id=appointment.id,
        consultation_id=consultation_id,
        order_number=number,
        priority=data.priority,
        clinical_note=data.clinical_note,
        created_by=actor.user_id,
    )
    session.add(order)
    await session.flush()
    for position, test_id in enumerate(wanted):
        test = tests[test_id]
        session.add(
            LabOrderItem(
                order_id=order.id,
                test_id=test.id,
                test_code=test.code,
                test_name=test.name,
                sort_order=position,
            )
        )
    add_event(session, order, "ordered", actor.user_id)
    await session.flush()
    return success(order)


async def cancel_items(
    session: AsyncSession,
    actor: StaffActor,
    order_id: UUID,
    item_ids: Sequence[UUID] | None,
    reason: str | None,
) -> BookingResult[LabOrder]:
    """Cancel some (or, with item_ids=None, all still-ordered) tests of an order."""
    result = await _cancel_items(session, actor, order_id, item_ids, reason)
    if result.ok:
        await session.commit()
    else:
        await session.rollback()
    return result


async def _cancel_items(
    session: AsyncSession,
    actor: StaffActor,
    order_id: UUID,
    item_ids: Sequence[UUID] | None,
    reason: str | None,
) -> BookingResult[LabOrder]:
    if actor.is_lab:
        if not reason:
            return failure(BookingErrorCode.VALIDATION, "Give a reason for cancelling.")
    else:
        check = clinician_check(actor)
        if not check.ok:
            return failure(check.code or BookingErrorCode.FORBIDDEN, check.message)

    order = await load_order(session, actor.clinic_id, order_id, lock=True)
    if order is None:
        return failure(BookingErrorCode.NOT_FOUND, ORDER_NOT_FOUND)
    if not actor.is_lab and order.ordering_doctor_id != actor.doctor_id:
        return failure(
            BookingErrorCode.FORBIDDEN, "Only the doctor who ordered these tests can cancel them."
        )

    items = await order_items(session, order.id)
    if item_ids is None:
        targets = [i for i in items if i.status == LabItemStatus.ORDERED]
        if not targets:
            return failure(
                BookingErrorCode.INVALID_TRANSITION,
                "Nothing to cancel: every test has a sample collected or is finished.",
            )
    else:
        by_id = {i.id: i for i in items}
        if any(i not in by_id for i in item_ids) or not item_ids:
            return failure(BookingErrorCode.NOT_FOUND, "Lab test not found.")
        targets = [by_id[i] for i in dict.fromkeys(item_ids)]
        if any(t.status != LabItemStatus.ORDERED for t in targets):
            return failure(
                BookingErrorCode.INVALID_TRANSITION,
                "Only tests whose sample has not been collected can be cancelled.",
            )

    for item in targets:
        item.cancelled_reason = reason
        move(session, order, item, LabItemStatus.CANCELLED, "cancelled", actor.user_id)
    await refresh_order(session, order)
    if order.status == LabOrderStatus.CANCELLED:
        order.cancelled_reason = reason
    return success(order)


async def last_order_test_ids(
    session: AsyncSession, actor: StaffActor, patient_id: UUID
) -> BookingResult[list[UUID]]:
    """Tests of the patient's most recent order (for "Repeat last order"), still orderable."""
    check = clinician_check(actor)
    if not check.ok:
        return failure(check.code or BookingErrorCode.FORBIDDEN, check.message)
    last = await session.scalar(
        select(LabOrder.id)
        .where(LabOrder.clinic_id == actor.clinic_id, LabOrder.patient_id == patient_id)
        .order_by(LabOrder.created_at.desc())
        .limit(1)
    )
    if last is None:
        return success([])
    rows = await session.scalars(
        select(LabOrderItem.test_id)
        .join(LabTest, LabTest.id == LabOrderItem.test_id)
        .where(LabOrderItem.order_id == last, LabTest.is_active)
        .order_by(LabOrderItem.sort_order)
    )
    return success(list(rows.all()))
