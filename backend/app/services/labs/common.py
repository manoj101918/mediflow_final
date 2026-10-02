"""Shared helpers for the lab services: access checks, loading, events, order status."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Clinic, LabItemStatus, LabOrder, LabOrderEvent, LabOrderItem, UserRole
from app.services.booking.actor import StaffActor
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success
from app.services.booking.timeutil import clinic_tz, utcnow
from app.services.labs.transitions import derive_order_status

NOT_LAB = "Only lab staff can do this."
ORDER_NOT_FOUND = "Lab order not found."


@dataclass(frozen=True)
class ClinicLabSettings:
    tz: ZoneInfo
    requires_verification: bool
    name: str


async def clinic_settings(session: AsyncSession, clinic_id: UUID) -> ClinicLabSettings:
    clinic = await session.get(Clinic, clinic_id)
    if clinic is None:  # pragma: no cover - actors always belong to an existing clinic
        return ClinicLabSettings(clinic_tz(), True, "")
    return ClinicLabSettings(
        clinic_tz(clinic.timezone), clinic.lab_requires_verification, clinic.name
    )


def lab_check(actor: StaffActor) -> BookingResult[None]:
    if actor.role not in (UserRole.LAB_TECHNICIAN, UserRole.LAB_SUPERVISOR):
        return failure(BookingErrorCode.FORBIDDEN, NOT_LAB)
    return success(None)


async def load_order(
    session: AsyncSession, clinic_id: UUID, order_id: UUID, *, lock: bool = False
) -> LabOrder | None:
    query = select(LabOrder).where(LabOrder.id == order_id, LabOrder.clinic_id == clinic_id)
    if lock:
        query = query.with_for_update()
    return await session.scalar(query)


async def order_items(session: AsyncSession, order_id: UUID) -> list[LabOrderItem]:
    return list(
        (
            await session.scalars(
                select(LabOrderItem)
                .where(LabOrderItem.order_id == order_id)
                .order_by(LabOrderItem.sort_order, LabOrderItem.test_name)
            )
        ).all()
    )


@dataclass(frozen=True)
class LockedItem:
    order: LabOrder
    item: LabOrderItem


async def lock_item(
    session: AsyncSession, clinic_id: UUID, item_id: UUID
) -> BookingResult[LockedItem]:
    """The item and its order, both locked (order first, the same order every writer uses)."""
    order_id = await session.scalar(select(LabOrderItem.order_id).where(LabOrderItem.id == item_id))
    order = await load_order(session, clinic_id, order_id, lock=True) if order_id else None
    if order is None:
        return failure(BookingErrorCode.NOT_FOUND, "Lab test not found.")
    item = await session.scalar(
        select(LabOrderItem).where(LabOrderItem.id == item_id).with_for_update()
    )
    if item is None:  # pragma: no cover - deleted between the two reads
        return failure(BookingErrorCode.NOT_FOUND, "Lab test not found.")
    return success(LockedItem(order, item))


def add_event(
    session: AsyncSession,
    order: LabOrder,
    event: str,
    actor_id: UUID | None,
    *,
    item: LabOrderItem | None = None,
    from_status: LabItemStatus | None = None,
    to_status: LabItemStatus | None = None,
) -> None:
    """Audit row (ids and statuses only, never values)."""
    session.add(
        LabOrderEvent(
            clinic_id=order.clinic_id,
            order_id=order.id,
            order_item_id=item.id if item else None,
            event=event,
            from_status=from_status.value if from_status else None,
            to_status=to_status.value if to_status else None,
            actor_id=actor_id,
        )
    )


def move(
    session: AsyncSession,
    order: LabOrder,
    item: LabOrderItem,
    target: LabItemStatus,
    event: str,
    actor_id: UUID | None,
) -> None:
    """Set an item's status and record the change."""
    previous = item.status
    item.status = target
    add_event(session, order, event, actor_id, item=item, from_status=previous, to_status=target)


async def refresh_order(session: AsyncSession, order: LabOrder) -> None:
    """Derive the order status from its items and touch updated_at (Realtime ping)."""
    await session.flush()
    statuses: Sequence[LabItemStatus] = (
        await session.scalars(select(LabOrderItem.status).where(LabOrderItem.order_id == order.id))
    ).all()
    order.status = derive_order_status(statuses)
    # Any change counts: the DB trigger stamps now() and RETURNING brings it back.
    order.updated_at = utcnow()
    await session.flush()
