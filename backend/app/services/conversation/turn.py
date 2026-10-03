"""Run one conversation turn and persist it.

Per turn: load (or create) the conversation, let the engine handle the message, then in ONE
transaction save the new state with an optimistic version check, record the side effects,
queue the replies in the outbox (idempotent by inbound message) and mark the inbound
message processed. If another turn saved first, the turn is re-run once on the fresh state;
bookings are idempotent per attempt (external_ref), so re-running never books twice.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BotAlert,
    BotChannel,
    BotConversation,
    ChannelMessage,
    ChannelMessageStatus,
    ConsentEvent,
    ContactPreference,
    HandoffStatus,
    MessageOutbox,
)
from app.services.booking.timeutil import utcnow
from app.services.conversation import data, engine
from app.services.conversation.intent import Understander
from app.services.conversation.keywords import KeywordSet, load_keywords
from app.services.conversation.types import (
    ConvState,
    InboundMsg,
    Language,
    OpenHandoff,
    RaiseAlert,
    RecordConsent,
    Reply,
    SetOptOut,
    TurnOutcome,
)


class ConversationBusyError(RuntimeError):
    """Another turn kept winning the version race (retry the job later)."""


@dataclass(frozen=True)
class TurnResult:
    conversation_id: UUID
    replies: list[Reply]
    outbox_ids: list[UUID] = field(default_factory=list)
    appointment_id: UUID | None = None
    ignored: bool = False
    state: str = ""


def snapshot(row: BotConversation) -> ConvState:
    return ConvState(
        id=row.id,
        clinic_id=row.clinic_id,
        channel=row.channel,
        phone_e164=row.phone_e164,
        state=row.state,
        language=cast(Language | None, row.language),
        selected_patient_id=row.selected_patient_id,
        draft=dict(row.draft or {}),
        attempt_counter=row.attempt_counter,
        failed_parse_count=row.failed_parse_count,
        handoff_open=row.handoff_status is HandoffStatus.OPEN,
        last_message_ts=row.last_message_ts,
        version=row.version,
    )


async def load_conversation(
    session: AsyncSession, clinic_id: UUID, channel: BotChannel, phone: str
) -> ConvState:
    """The conversation for this sender, created (and committed) on first contact."""
    await session.execute(
        insert(BotConversation)
        .values(clinic_id=clinic_id, channel=channel, phone_e164=phone)
        .on_conflict_do_nothing(index_elements=["clinic_id", "channel", "phone_e164"])
    )
    await session.commit()
    row = await session.scalar(
        select(BotConversation)
        .where(
            BotConversation.clinic_id == clinic_id,
            BotConversation.channel == channel,
            BotConversation.phone_e164 == phone,
        )
        .execution_options(populate_existing=True)
    )
    assert row is not None  # noqa: S101 - inserted above
    return snapshot(row)


async def run_turn(
    session: AsyncSession,
    clinic_id: UUID,
    msg: InboundMsg,
    *,
    notice_version: str,
    now: datetime | None = None,
    keywords: KeywordSet | None = None,
    extras: dict[str, Any] | None = None,
    understand: Understander | None = None,
) -> TurnResult:
    moment = now or utcnow()
    words = keywords or await load_keywords(session, clinic_id)
    clinic = await data.clinic_info(session, clinic_id)
    ctx = engine.TurnContext(
        clinic_id=clinic_id,
        clinic_name=clinic.name,
        tz=clinic.tz,
        now=moment,
        keywords=words,
        opted_out=await is_opted_out(session, clinic_id, msg.phone_e164),
        extras=extras or {},
        understand=understand,
    )
    for _ in range(2):
        conv = await load_conversation(session, clinic_id, msg.channel, msg.phone_e164)
        outcome = await engine.handle(session, ctx, conv, msg)
        outbox_ids = await _persist(session, conv, outcome, msg, moment, notice_version)
        if outbox_ids is not None:
            return TurnResult(
                conversation_id=conv.id,
                replies=outcome.replies,
                outbox_ids=outbox_ids,
                appointment_id=outcome.appointment_id,
                ignored=outcome.ignored,
                state=outcome.state.state,
            )
        await session.rollback()
    raise ConversationBusyError(str(msg.message_id))


async def _persist(
    session: AsyncSession,
    before: ConvState,
    outcome: TurnOutcome,
    msg: InboundMsg,
    now: datetime,
    notice_version: str,
) -> list[UUID] | None:
    """Save everything in one transaction; None if the conversation changed meanwhile."""
    state = outcome.state
    values: dict[str, Any] = {
        "state": state.state,
        "language": state.language,
        "selected_patient_id": state.selected_patient_id,
        "draft": state.draft,
        "attempt_counter": state.attempt_counter,
        "failed_parse_count": state.failed_parse_count,
        "last_message_ts": state.last_message_ts,
        "last_inbound_at": now,
        "version": before.version + 1,
    }
    handoff = next((e for e in outcome.effects if isinstance(e, OpenHandoff)), None)
    if handoff is not None:
        values |= {
            "handoff_status": HandoffStatus.OPEN,
            "handoff_reason": handoff.reason,
            "handoff_at": now,
        }
    saved = await session.execute(
        update(BotConversation)
        .where(BotConversation.id == before.id, BotConversation.version == before.version)
        .values(**values)
    )
    if saved.rowcount == 0:  # type: ignore[attr-defined]
        return None

    for effect in outcome.effects:
        if isinstance(effect, RaiseAlert):
            session.add(
                BotAlert(
                    clinic_id=before.clinic_id,
                    conversation_id=before.id,
                    message_id=msg.message_id,
                    kind=effect.kind,
                )
            )
        elif isinstance(effect, RecordConsent):
            session.add(
                ConsentEvent(
                    clinic_id=before.clinic_id,
                    phone_e164=before.phone_e164,
                    patient_id=state.selected_patient_id,
                    channel=before.channel,
                    notice_version=notice_version,
                    action=effect.action,
                    evidence=msg.external_id,
                )
            )
            if effect.action == "consented":
                await set_preference(
                    session,
                    before.clinic_id,
                    before.phone_e164,
                    before.channel,
                    now,
                    opted_out=False,
                )
        elif isinstance(effect, SetOptOut):
            await set_preference(
                session,
                before.clinic_id,
                before.phone_e164,
                before.channel,
                now,
                opted_out=effect.opted_out,
            )

    outbox_ids: list[UUID] = []
    key_base = msg.message_id or uuid4()
    for index, reply in enumerate(outcome.replies):
        inserted = await session.scalar(
            insert(MessageOutbox)
            .values(
                clinic_id=before.clinic_id,
                conversation_id=before.id,
                appointment_id=outcome.appointment_id,
                channel=before.channel,
                phone_e164=before.phone_e164,
                kind=reply.kind,
                essential=reply.essential,
                idempotency_key=f"reply:{key_base}:{index}",
                body=reply.as_body(),
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(MessageOutbox.id)
        )
        if inserted is not None:
            outbox_ids.append(inserted)

    if msg.message_id is not None:
        await session.execute(
            update(ChannelMessage)
            .where(ChannelMessage.id == msg.message_id)
            .values(
                conversation_id=before.id,
                status=(
                    ChannelMessageStatus.IGNORED
                    if outcome.ignored
                    else ChannelMessageStatus.PROCESSED
                ),
            )
        )
    await session.commit()
    return outbox_ids


async def set_preference(
    session: AsyncSession,
    clinic_id: UUID,
    phone: str,
    channel: BotChannel,
    now: datetime,
    *,
    opted_out: bool,
) -> None:
    """Opt a phone in or out. An opt-out covers every channel (one row per phone)."""
    values: dict[str, Any] = {"channel": channel, "updated_at": now}
    if opted_out:
        values["opted_out_at"] = now
    else:
        values |= {"opted_in_at": now, "opted_in_source": channel.value, "opted_out_at": None}
    await session.execute(
        insert(ContactPreference)
        .values(clinic_id=clinic_id, phone_e164=phone, **values)
        .on_conflict_do_update(index_elements=["clinic_id", "phone_e164"], set_=values)
    )


async def is_opted_out(session: AsyncSession, clinic_id: UUID, phone: str) -> bool:
    opted_out_at = await session.scalar(
        select(ContactPreference.opted_out_at).where(
            ContactPreference.clinic_id == clinic_id, ContactPreference.phone_e164 == phone
        )
    )
    return opted_out_at is not None
