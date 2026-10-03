"""Admin view of the bot: WhatsApp connection, webhook activity and the free-tier meter."""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import BotJob
from app.services.messaging.dispatch import month_start, usage_this_month

WARN_RATIO = 0.8


@dataclass(frozen=True)
class Usage:
    month: date
    sent: int
    limit: int
    reserve_from: int
    warn: bool
    exhausted: bool


async def usage(session: AsyncSession, clinic_id: UUID, settings: Settings, now: datetime) -> Usage:
    sent = await usage_this_month(session, clinic_id, now)
    limit = settings.bot_free_reply_limit
    return Usage(
        month=month_start(now),
        sent=sent,
        limit=limit,
        reserve_from=max(limit - settings.bot_essential_reserve, 0),
        warn=limit > 0 and sent >= WARN_RATIO * limit,
        exhausted=sent >= limit,
    )


async def webhook_last_seen(session: AsyncSession, clinic_id: UUID) -> datetime | None:
    """When Meta last delivered anything (a message or a status) for this clinic."""
    return await session.scalar(
        select(func.max(BotJob.created_at)).where(
            BotJob.clinic_id == clinic_id, BotJob.kind.in_(("inbound", "status"))
        )
    )
