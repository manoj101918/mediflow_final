"""Human-readable lab order numbers and sample codes.

Both are sequential per clinic per clinic-local day, assigned under a transaction-scoped
advisory lock (like booking tokens), so concurrent orders never share a number. Numbers are
never reused: cancelled orders keep theirs.

    order number  LAB-20261002-0007
    sample code   S-261002-0042
"""

from datetime import date
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LabOrder, LabSample


async def _lock(session: AsyncSession, kind: str, clinic_id: UUID, day: date) -> None:
    await session.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"{kind}:{clinic_id}:{day.isoformat()}"},
    )


def _next(current: str | None) -> int:
    return int(current.rsplit("-", 1)[1]) + 1 if current else 1


async def next_order_number(session: AsyncSession, clinic_id: UUID, day: date) -> str:
    """Locks the clinic's order sequence for `day` until the transaction ends."""
    await _lock(session, "lab-order", clinic_id, day)
    prefix = f"LAB-{day:%Y%m%d}-"
    current = await session.scalar(
        select(LabOrder.order_number)
        .where(LabOrder.clinic_id == clinic_id, LabOrder.order_number.startswith(prefix))
        # Longest first: text order would put "-10000" before "-9999".
        .order_by(func.length(LabOrder.order_number).desc(), LabOrder.order_number.desc())
        .limit(1)
    )
    return f"{prefix}{_next(current):04d}"


async def next_sample_code(session: AsyncSession, clinic_id: UUID, day: date) -> str:
    """Locks the clinic's sample sequence for `day` until the transaction ends."""
    await _lock(session, "lab-sample", clinic_id, day)
    prefix = f"S-{day:%y%m%d}-"
    current = await session.scalar(
        select(LabSample.sample_code)
        .where(LabSample.clinic_id == clinic_id, LabSample.sample_code.startswith(prefix))
        # Longest first: text order would put "-10000" before "-9999".
        .order_by(func.length(LabSample.sample_code).desc(), LabSample.sample_code.desc())
        .limit(1)
    )
    return f"{prefix}{_next(current):04d}"
