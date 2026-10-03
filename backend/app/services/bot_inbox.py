"""Reception's side of the bot: handed-off conversations, transcripts, replies, alerts.

Everything is scoped to the staff member's clinic. Replies from reception are free-form
WhatsApp messages, so they need an open 24-hour window and a phone that hasn't opted out.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appointment,
    AppointmentSource,
    BotAlert,
    BotChannel,
    BotConversation,
    ChannelMessage,
    ContactPreference,
    HandoffStatus,
    MessageOutbox,
    Patient,
)
from app.services.bot_jobs import queue
from app.services.conversation.engine import MENU
from app.services.conversation.i18n import first_name
from app.services.messaging.dispatch import DispatchDeps, SendError, dispatch, window_open

MAX_MESSAGES = 200


@dataclass(frozen=True)
class ConversationSummary:
    id: UUID
    channel: BotChannel
    phone_e164: str
    names: list[str]
    language: str | None
    state: str
    handoff_status: HandoffStatus
    handoff_reason: str | None
    handoff_at: datetime | None
    last_inbound_at: datetime | None
    last_message: str | None
    window_open: bool
    opted_out: bool
    open_alerts: int
    emergency: bool


@dataclass(frozen=True)
class TranscriptMessage:
    id: UUID
    direction: str
    type: str
    text: str | None
    transcript: str | None
    status: str
    created_at: datetime


@dataclass(frozen=True)
class ConversationDetail:
    summary: ConversationSummary
    messages: list[TranscriptMessage]


@dataclass(frozen=True)
class AlertInfo:
    id: UUID
    kind: str
    conversation_id: UUID
    channel: BotChannel
    phone_e164: str
    names: list[str]
    excerpt: str | None
    created_at: datetime


async def _names(session: AsyncSession, clinic_id: UUID, phone: str) -> list[str]:
    rows = await session.scalars(
        select(Patient.full_name)
        .where(Patient.clinic_id == clinic_id, Patient.phone == phone)
        .order_by(Patient.created_at)
        .limit(5)
    )
    return [first_name(name) for name in rows]


async def _summary(
    session: AsyncSession, row: BotConversation, now: datetime
) -> ConversationSummary:
    last_message = await session.scalar(
        select(func.coalesce(ChannelMessage.transcript, ChannelMessage.body_text))
        .where(ChannelMessage.conversation_id == row.id)
        .order_by(ChannelMessage.created_at.desc())
        .limit(1)
    )
    alerts = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.bool_or(BotAlert.kind == "emergency"), False),
            ).where(BotAlert.conversation_id == row.id, BotAlert.acknowledged_at.is_(None))
        )
    ).one()
    opted_out_at = await session.scalar(
        select(ContactPreference.opted_out_at).where(
            ContactPreference.clinic_id == row.clinic_id,
            ContactPreference.phone_e164 == row.phone_e164,
        )
    )
    is_whatsapp = row.channel is BotChannel.WHATSAPP
    return ConversationSummary(
        id=row.id,
        channel=row.channel,
        phone_e164=row.phone_e164,
        names=await _names(session, row.clinic_id, row.phone_e164),
        language=row.language,
        state=row.state,
        handoff_status=row.handoff_status,
        handoff_reason=row.handoff_reason,
        handoff_at=row.handoff_at,
        last_inbound_at=row.last_inbound_at,
        last_message=(last_message or "")[:200] or None,
        window_open=(
            await window_open(session, row.clinic_id, row.phone_e164, now) if is_whatsapp else True
        ),
        opted_out=opted_out_at is not None,
        open_alerts=int(alerts[0]),
        emergency=bool(alerts[1]),
    )


async def list_conversations(
    session: AsyncSession, clinic_id: UUID, now: datetime, *, handoff_only: bool
) -> list[ConversationSummary]:
    """Handed-off conversations (emergencies first), or the most recent ones."""
    emergency_first = (
        select(func.count())
        .where(
            BotAlert.conversation_id == BotConversation.id,
            BotAlert.kind == "emergency",
            BotAlert.acknowledged_at.is_(None),
        )
        .scalar_subquery()
    )
    stmt = select(BotConversation).where(BotConversation.clinic_id == clinic_id)
    if handoff_only:
        stmt = stmt.where(BotConversation.handoff_status == HandoffStatus.OPEN).order_by(
            case((emergency_first > 0, 0), else_=1), BotConversation.handoff_at.desc()
        )
    else:
        stmt = stmt.order_by(BotConversation.updated_at.desc())
    rows = list(await session.scalars(stmt.limit(50)))
    return [await _summary(session, row, now) for row in rows]


async def _conversation(
    session: AsyncSession, clinic_id: UUID, conversation_id: UUID
) -> BotConversation | None:
    return await session.scalar(
        select(BotConversation).where(
            BotConversation.id == conversation_id, BotConversation.clinic_id == clinic_id
        )
    )


async def conversation_detail(
    session: AsyncSession, clinic_id: UUID, conversation_id: UUID, now: datetime
) -> ConversationDetail | None:
    row = await _conversation(session, clinic_id, conversation_id)
    if row is None:
        return None
    messages = await session.scalars(
        select(ChannelMessage)
        .where(ChannelMessage.conversation_id == row.id)
        .order_by(ChannelMessage.created_at.desc())
        .limit(MAX_MESSAGES)
    )
    transcript = [
        TranscriptMessage(
            id=m.id,
            direction=m.direction.value,
            type=m.type,
            text=m.body_text,
            transcript=m.transcript,
            status=m.status.value,
            created_at=m.created_at,
        )
        for m in reversed(list(messages))
    ]
    return ConversationDetail(summary=await _summary(session, row, now), messages=transcript)


async def conversation_for_appointment(
    session: AsyncSession, clinic_id: UUID, appointment_id: UUID
) -> UUID | None:
    """The bot conversation a WhatsApp / voice booking came from (for "View chat")."""
    row = (
        await session.execute(
            select(Appointment.source, Patient.phone)
            .join(Patient, Patient.id == Appointment.patient_id)
            .where(Appointment.id == appointment_id, Appointment.clinic_id == clinic_id)
        )
    ).first()
    if row is None:
        return None
    channel = {
        AppointmentSource.WHATSAPP: BotChannel.WHATSAPP,
        AppointmentSource.VOICE: BotChannel.WEB_VOICE,
    }.get(row.source)
    if channel is None:
        return None
    return await session.scalar(
        select(BotConversation.id).where(
            BotConversation.clinic_id == clinic_id,
            BotConversation.channel == channel,
            BotConversation.phone_e164 == row.phone,
        )
    )


ReplyOutcome = Literal["sent", "queued", "window_closed", "opted_out", "blocked", "not_found"]


async def staff_reply(
    session: AsyncSession,
    clinic_id: UUID,
    conversation_id: UUID,
    user_id: UUID,
    text: str,
    deps: DispatchDeps,
    now: datetime,
) -> ReplyOutcome:
    row = await _conversation(session, clinic_id, conversation_id)
    if row is None:
        return "not_found"
    conversation_id, channel, phone = row.id, row.channel, row.phone_e164
    opted_out = await session.scalar(
        select(ContactPreference.opted_out_at).where(
            ContactPreference.clinic_id == clinic_id, ContactPreference.phone_e164 == phone
        )
    )
    if opted_out is not None:
        return "opted_out"
    if channel is BotChannel.WHATSAPP and not await window_open(session, clinic_id, phone, now):
        return "window_closed"
    outbox = MessageOutbox(
        clinic_id=clinic_id,
        conversation_id=conversation_id,
        channel=channel,
        phone_e164=phone,
        kind="staff_reply",
        essential=True,
        idempotency_key=f"staff:{uuid4()}",
        body={"text": text},
    )
    session.add(outbox)
    await session.execute(
        update(BotConversation)
        .where(BotConversation.id == conversation_id)
        .values(assigned_to=user_id)
    )
    await session.commit()
    outbox_id = outbox.id
    try:
        status = await dispatch(session, deps, outbox_id, now)
    except SendError:
        await queue.enqueue(session, clinic_id, "outbox", ref_id=outbox_id)
        await session.commit()
        return "queued"
    return "sent" if status.value == "sent" else "blocked"


async def resume_bot(session: AsyncSession, clinic_id: UUID, conversation_id: UUID) -> bool:
    """Close the handoff: the bot answers the patient's next message with the menu."""
    result = await session.execute(
        update(BotConversation)
        .where(BotConversation.id == conversation_id, BotConversation.clinic_id == clinic_id)
        .values(
            handoff_status=HandoffStatus.RESOLVED,
            state=MENU,
            draft={},
            failed_parse_count=0,
            version=BotConversation.version + 1,
        )
    )
    await session.execute(
        update(BotAlert)
        .where(
            BotAlert.conversation_id == conversation_id,
            BotAlert.kind == "handoff",
            BotAlert.acknowledged_at.is_(None),
        )
        .values(acknowledged_at=func.now())
    )
    await session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def open_alerts(session: AsyncSession, clinic_id: UUID) -> list[AlertInfo]:
    rows = await session.execute(
        select(BotAlert, BotConversation.channel, BotConversation.phone_e164, ChannelMessage)
        .join(BotConversation, BotConversation.id == BotAlert.conversation_id)
        .outerjoin(ChannelMessage, ChannelMessage.id == BotAlert.message_id)
        .where(BotAlert.clinic_id == clinic_id, BotAlert.acknowledged_at.is_(None))
        .order_by(case((BotAlert.kind == "emergency", 0), else_=1), BotAlert.created_at.desc())
        .limit(50)
    )
    alerts: list[AlertInfo] = []
    for alert, channel, phone, message in rows:
        excerpt = (message.transcript or message.body_text) if message is not None else None
        alerts.append(
            AlertInfo(
                id=alert.id,
                kind=alert.kind,
                conversation_id=alert.conversation_id,
                channel=channel,
                phone_e164=phone,
                names=await _names(session, clinic_id, phone),
                excerpt=(excerpt or "")[:300] or None,
                created_at=alert.created_at,
            )
        )
    return alerts


async def acknowledge_alert(
    session: AsyncSession, clinic_id: UUID, alert_id: UUID, user_id: UUID
) -> bool:
    result = await session.execute(
        update(BotAlert)
        .where(
            BotAlert.id == alert_id,
            BotAlert.clinic_id == clinic_id,
            BotAlert.acknowledged_at.is_(None),
        )
        .values(acknowledged_at=func.now(), acknowledged_by=user_id)
    )
    await session.commit()
    return bool(result.rowcount)  # type: ignore[attr-defined]
