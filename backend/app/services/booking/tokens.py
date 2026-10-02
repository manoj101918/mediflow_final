"""Per-doctor, per-day token numbers.

Tokens are assigned under a transaction-scoped advisory lock keyed on (doctor, day), so
concurrent bookings for the same doctor and day are serialized. Tokens are never reused:
cancelled appointments keep theirs and the next booking gets max + 1.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Appointment


async def lock_doctor_day(session: AsyncSession, doctor_id: UUID, day: date) -> None:
    """Block until no other transaction is booking this doctor on this day."""
    await session.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"booking:{doctor_id}:{day.isoformat()}"},
    )


async def next_token(session: AsyncSession, doctor_id: UUID, day: date) -> int:
    """Next token for the doctor/day. Call only while holding lock_doctor_day."""
    current = await session.scalar(
        select(func.max(Appointment.token_number)).where(
            Appointment.doctor_id == doctor_id, Appointment.appointment_date == day
        )
    )
    return (current or 0) + 1
