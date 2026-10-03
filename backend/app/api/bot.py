"""Reception: the bot handoff inbox, chat transcripts, replies and emergency alerts."""

from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.results import not_found
from app.core.errors import AppError
from app.deps import BotDispatch, DbSession, FrontDeskUser
from app.schemas.bot import (
    AppointmentConversationOut,
    BotAlertOut,
    ConversationDetailOut,
    ConversationSummaryOut,
    StaffReplyIn,
    StaffReplyOut,
    TranscriptMessageOut,
)
from app.services import bot_inbox
from app.services.booking.timeutil import utcnow

router = APIRouter(prefix="/bot", tags=["bot"])


def _summary_out(summary: bot_inbox.ConversationSummary) -> ConversationSummaryOut:
    data = asdict(summary)
    return ConversationSummaryOut(
        **{k: v for k, v in data.items() if k not in ("phone_e164", "channel", "handoff_status")},
        phone=summary.phone_e164,
        channel=summary.channel.value,
        handoff_status=summary.handoff_status.value,
    )


@router.get("/conversations")
async def list_conversations(
    session: DbSession,
    user: FrontDeskUser,
    handoff: Annotated[bool, Query(description="Only conversations waiting for reception")] = True,
) -> list[ConversationSummaryOut]:
    rows = await bot_inbox.list_conversations(
        session, user.clinic_id, utcnow(), handoff_only=handoff
    )
    return [_summary_out(row) for row in rows]


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: UUID, session: DbSession, user: FrontDeskUser
) -> ConversationDetailOut:
    detail = await bot_inbox.conversation_detail(session, user.clinic_id, conversation_id, utcnow())
    if detail is None:
        raise not_found("Conversation")
    return ConversationDetailOut(
        **_summary_out(detail.summary).model_dump(),
        messages=[TranscriptMessageOut(**asdict(m)) for m in detail.messages],
    )


@router.post("/conversations/{conversation_id}/reply")
async def reply(
    conversation_id: UUID,
    body: StaffReplyIn,
    session: DbSession,
    user: FrontDeskUser,
    deps: BotDispatch,
) -> StaffReplyOut:
    outcome = await bot_inbox.staff_reply(
        session, user.clinic_id, conversation_id, user.id, body.text.strip(), deps, utcnow()
    )
    if outcome == "not_found":
        raise not_found("Conversation")
    if outcome == "window_closed":
        raise AppError(
            409, "WINDOW_CLOSED", "WhatsApp's 24-hour window is closed. Call the patient."
        )
    if outcome == "opted_out":
        raise AppError(409, "OPTED_OUT", "The patient opted out of messages. Call the patient.")
    return StaffReplyOut(status=outcome)


@router.post("/conversations/{conversation_id}/resume", status_code=status.HTTP_204_NO_CONTENT)
async def resume(conversation_id: UUID, session: DbSession, user: FrontDeskUser) -> None:
    if not await bot_inbox.resume_bot(session, user.clinic_id, conversation_id):
        raise not_found("Conversation")


@router.get("/appointments/{appointment_id}/conversation")
async def appointment_conversation(
    appointment_id: UUID, session: DbSession, user: FrontDeskUser
) -> AppointmentConversationOut:
    conversation_id = await bot_inbox.conversation_for_appointment(
        session, user.clinic_id, appointment_id
    )
    return AppointmentConversationOut(conversation_id=conversation_id)


@router.get("/alerts")
async def alerts(session: DbSession, user: FrontDeskUser) -> list[BotAlertOut]:
    rows = await bot_inbox.open_alerts(session, user.clinic_id)
    return [
        BotAlertOut(
            id=a.id,
            kind=a.kind,
            conversation_id=a.conversation_id,
            channel=a.channel.value,
            phone=a.phone_e164,
            names=a.names,
            excerpt=a.excerpt,
            created_at=a.created_at,
        )
        for a in rows
    ]


@router.post("/alerts/{alert_id}/ack", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge(alert_id: UUID, session: DbSession, user: FrontDeskUser) -> None:
    if not await bot_inbox.acknowledge_alert(session, user.clinic_id, alert_id, user.id):
        raise not_found("Alert")
