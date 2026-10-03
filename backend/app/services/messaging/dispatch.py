"""Send queued messages (table `message_outbox`) safely and for free.

Every WhatsApp send is checked, in order:
1. the phone has not opted out (any channel), except the opt-out confirmation itself;
2. consent was recorded, except the privacy notice, the opt-out confirmation and the
   emergency reply (safety first);
3. the 24-hour customer-service window is open (an inbound message from that phone in the
   last 24 h). Outside it only paid templates could be sent, and those are not built;
4. the monthly free allowance: non-essential messages stop at `limit - reserve`, essential
   ones (confirmations, emergencies, opt-out, handoff) may use the reserve; nothing is sent
   at the limit (Meta stops delivering past its free tier without a payment method).

A message that fails a check is `blocked` with the reason and never retried. Sends are
idempotent: only `pending` rows are sent, under a row lock.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import Text, case, cast, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BotChannel,
    BotUsageMonthly,
    ChannelMessage,
    ChannelMessageStatus,
    ConsentEvent,
    ContactPreference,
    MessageDirection,
    MessageOutbox,
    OutboxStatus,
)

WINDOW = timedelta(hours=24)
# Exempt from the consent check: they are sent before (or instead of) consent.
CONSENT_EXEMPT = frozenset({"notice", "opt_out", "emergency"})


class SendError(Exception):
    """A channel refused or failed to send. `permanent` errors are not retried."""

    def __init__(self, message: str, *, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent


class ChannelSender(Protocol):
    async def send(self, phone_e164: str, body: dict[str, Any]) -> str:
        """Send one message; returns the channel's message id (wamid)."""
        ...


@dataclass(frozen=True)
class DispatchDeps:
    whatsapp: ChannelSender | None
    free_limit: int
    essential_reserve: int
    max_attempts: int = 5


def month_start(moment: datetime) -> date:
    return date(moment.year, moment.month, 1)


async def window_open(session: AsyncSession, clinic_id: UUID, phone: str, now: datetime) -> bool:
    last = await session.scalar(
        select(func.max(ChannelMessage.created_at)).where(
            ChannelMessage.clinic_id == clinic_id,
            ChannelMessage.channel == BotChannel.WHATSAPP,
            ChannelMessage.direction == MessageDirection.INBOUND,
            ChannelMessage.phone_e164 == phone,
        )
    )
    return last is not None and last > now - WINDOW


async def usage_this_month(
    session: AsyncSession, clinic_id: UUID, now: datetime, channel: BotChannel = BotChannel.WHATSAPP
) -> int:
    count = await session.scalar(
        select(BotUsageMonthly.sent_count).where(
            BotUsageMonthly.clinic_id == clinic_id,
            BotUsageMonthly.channel == channel,
            BotUsageMonthly.month == month_start(now),
        )
    )
    return count or 0


async def blocked_reason(
    session: AsyncSession, row: MessageOutbox, deps: DispatchDeps, now: datetime
) -> str | None:
    opted_out_at = await session.scalar(
        select(ContactPreference.opted_out_at).where(
            ContactPreference.clinic_id == row.clinic_id,
            ContactPreference.phone_e164 == row.phone_e164,
        )
    )
    if opted_out_at is not None and row.kind != "opt_out":
        return "opted_out"
    if row.kind not in CONSENT_EXEMPT:
        consented = await session.scalar(
            select(func.count())
            .select_from(ConsentEvent)
            .where(
                ConsentEvent.clinic_id == row.clinic_id,
                ConsentEvent.phone_e164 == row.phone_e164,
                ConsentEvent.action.in_(("consented", "opted_in")),
            )
        )
        if not consented:
            return "no_consent"
    if not await window_open(session, row.clinic_id, row.phone_e164, now):
        return "window_closed"
    if deps.whatsapp is None:
        return "not_configured"
    used = await usage_this_month(session, row.clinic_id, now)
    cutoff = deps.free_limit if row.essential else deps.free_limit - deps.essential_reserve
    if used >= cutoff:
        return "limit"
    return None


def _transcript_text(body: dict[str, Any]) -> str:
    lines = [str(body.get("text", ""))]
    options = body.get("buttons") or body.get("rows") or []
    lines += [f"• {option['title']}" for option in options]
    return "\n".join(line for line in lines if line)


async def _record_sent(
    session: AsyncSession, row: MessageOutbox, wamid: str | None, now: datetime
) -> None:
    session.add(
        ChannelMessage(
            clinic_id=row.clinic_id,
            conversation_id=row.conversation_id,
            direction=MessageDirection.OUTBOUND,
            channel=row.channel,
            phone_e164=row.phone_e164,
            wamid=wamid,
            type=row.kind,
            payload=row.body,
            body_text=_transcript_text(row.body),
            status=ChannelMessageStatus.SENT,
            message_ts=now,
        )
    )


async def _count_usage(session: AsyncSession, clinic_id: UUID, now: datetime) -> None:
    await session.execute(
        insert(BotUsageMonthly)
        .values(
            clinic_id=clinic_id, channel=BotChannel.WHATSAPP, month=month_start(now), sent_count=1
        )
        .on_conflict_do_update(
            index_elements=["clinic_id", "channel", "month"],
            set_={"sent_count": BotUsageMonthly.sent_count + 1, "updated_at": now},
        )
    )


async def dispatch(
    session: AsyncSession, deps: DispatchDeps, outbox_id: UUID, now: datetime
) -> OutboxStatus:
    """Send one queued message if every check passes. Raises SendError to retry later."""
    row = await session.scalar(
        select(MessageOutbox).where(MessageOutbox.id == outbox_id).with_for_update()
    )
    if row is None:
        await session.rollback()
        return OutboxStatus.FAILED
    if row.status is not OutboxStatus.PENDING:
        await session.rollback()
        return row.status

    if row.channel is not BotChannel.WHATSAPP:
        # Simulator (and later phone) replies are delivered in the HTTP response / call.
        await _record_sent(session, row, None, now)
        row.status, row.sent_at, row.attempts = OutboxStatus.SENT, now, row.attempts + 1
        await session.commit()
        return OutboxStatus.SENT

    reason = await blocked_reason(session, row, deps, now)
    if reason is not None:
        row.status, row.blocked_reason = OutboxStatus.BLOCKED, reason
        await session.commit()
        return OutboxStatus.BLOCKED

    assert deps.whatsapp is not None  # noqa: S101 - checked by _blocked_reason
    row.attempts += 1
    try:
        wamid = await deps.whatsapp.send(row.phone_e164, row.body)
    except SendError as exc:
        row.last_error = str(exc)[:500]
        give_up = exc.permanent or row.attempts >= deps.max_attempts
        if give_up:
            row.status = OutboxStatus.FAILED
        await session.commit()
        if give_up:
            return OutboxStatus.FAILED
        raise
    row.status, row.wamid, row.sent_at, row.last_error = OutboxStatus.SENT, wamid, now, None
    await _record_sent(session, row, wamid, now)
    await _count_usage(session, row.clinic_id, now)
    await session.commit()
    return OutboxStatus.SENT


# Delivery statuses only move forward: sent < delivered < read; failed is terminal.
_RANK = {"sent": 1, "delivered": 2, "read": 3, "failed": 4}


def _rank(column: Any) -> Any:
    return case(_RANK, value=cast(column, Text), else_=0)


async def apply_status(session: AsyncSession, wamid: str, status: str, error: str | None) -> bool:
    """Apply a delivery status to the message and its outbox row. False if neither exists yet."""
    rank = _RANK[status]
    message = await session.execute(
        update(ChannelMessage)
        .where(
            ChannelMessage.wamid == wamid,
            ChannelMessage.direction == MessageDirection.OUTBOUND,
            _rank(ChannelMessage.status) < rank,
        )
        .values(
            status=ChannelMessageStatus(status), error=func.coalesce(error, ChannelMessage.error)
        )
    )
    outbox = await session.execute(
        update(MessageOutbox)
        .where(MessageOutbox.wamid == wamid, _rank(MessageOutbox.status) < rank)
        .values(
            status=OutboxStatus(status), last_error=func.coalesce(error, MessageOutbox.last_error)
        )
    )
    if message.rowcount or outbox.rowcount:  # type: ignore[attr-defined]
        await session.commit()
        return True
    # Nothing moved forward: either an older status (fine) or the message isn't recorded yet.
    exists = await session.scalar(
        select(
            select(ChannelMessage.id).where(ChannelMessage.wamid == wamid).exists()
            | select(MessageOutbox.id).where(MessageOutbox.wamid == wamid).exists()
        )
    )
    await session.commit()
    return bool(exists)
