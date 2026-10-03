"""One spoken turn of the voice booking simulator: STT -> conversation engine -> TTS.

This is the free demo of the future phone agent. A telephony adapter (e.g. Pipecat + Plivo)
would do the same per caller utterance: transcribe, `run_turn` on its channel, deliver the
replies (`dispatch`), render them with `speakable`, synthesize. Bookings are real
`pending_confirmation` requests with source `voice`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BotChannel,
    BotConversation,
    ChannelMessage,
    ChannelMessageStatus,
    MessageDirection,
    MessageOutbox,
)
from app.services.booking.timeutil import utcnow
from app.services.conversation import InboundMsg, run_turn
from app.services.conversation.intent import Understander
from app.services.conversation.types import Language, Reply, VoiceError
from app.services.conversation.voice_style import speakable
from app.services.messaging.dispatch import DispatchDeps, dispatch
from app.services.speech.stt import SpeechToText, TranscriptionError
from app.services.speech.tts import Speech, TextToSpeech

CHANNEL = BotChannel.WEB_VOICE


@dataclass(frozen=True)
class VoiceDeps:
    stt: SpeechToText | None
    tts: TextToSpeech
    understand: Understander | None
    dispatch: DispatchDeps
    notice_version: str


@dataclass(frozen=True)
class SpokenTurn:
    transcript: str
    voice_error: VoiceError | None
    replies: list[Reply]
    speech_text: str
    speech: Speech
    appointment_id: UUID | None
    state: str
    ignored: bool


async def take_turn(
    session: AsyncSession,
    clinic_id: UUID,
    deps: VoiceDeps,
    *,
    phone: str,
    language: Language,
    text: str | None = None,
    reply_id: str | None = None,
    audio: bytes | None = None,
    mime_type: str = "audio/webm",
) -> SpokenTurn:
    had_audio = audio is not None
    transcript = (text or "").strip()
    voice_error: VoiceError | None = None
    if audio is not None:
        voice_error = "failed"
        if deps.stt is not None:
            try:
                transcript = (await deps.stt.transcribe(audio, mime_type, language)).text.strip()
                voice_error = None if transcript else "failed"
            except TranscriptionError as exc:
                voice_error = "too_long" if exc.too_long else "failed"
        del audio  # the recording is never stored

    message = ChannelMessage(
        clinic_id=clinic_id,
        direction=MessageDirection.INBOUND,
        channel=CHANNEL,
        phone_e164=phone,
        type="audio" if had_audio else ("interactive" if reply_id else "text"),
        payload={"reply_id": reply_id} if reply_id else {},
        body_text=transcript or None,
        transcript=(transcript or None) if had_audio else None,
        status=ChannelMessageStatus.RECEIVED,
    )
    session.add(message)
    await session.commit()
    message_id = message.id

    kind = "reply" if reply_id else ("voice" if had_audio else "text")
    result = await run_turn(
        session,
        clinic_id,
        InboundMsg(
            channel=CHANNEL,
            phone_e164=phone,
            kind=kind,  # type: ignore[arg-type]
            text=transcript,
            reply_id=reply_id,
            lang_hint=language,
            message_id=message_id,
            external_id=f"sim.{uuid.uuid4().hex}",
            voice_error=voice_error,
        ),
        notice_version=deps.notice_version,
        understand=deps.understand,
    )
    for outbox_id in result.outbox_ids:
        await dispatch(session, deps.dispatch, outbox_id, utcnow())

    spoken_language = await _language(session, clinic_id, phone) or language
    speech_text = speakable(result.replies, spoken_language)
    speech = (
        await deps.tts.synthesize(speech_text, spoken_language)
        if speech_text
        else Speech(None, None, "none")
    )
    return SpokenTurn(
        transcript=transcript,
        voice_error=voice_error,
        replies=result.replies,
        speech_text=speech_text,
        speech=speech,
        appointment_id=result.appointment_id,
        state=result.state,
        ignored=result.ignored,
    )


async def _language(session: AsyncSession, clinic_id: UUID, phone: str) -> Language | None:
    value = await session.scalar(
        select(BotConversation.language).where(
            BotConversation.clinic_id == clinic_id,
            BotConversation.channel == CHANNEL,
            BotConversation.phone_e164 == phone,
        )
    )
    return value if value in ("te", "hi", "en") else None  # type: ignore[return-value]


@dataclass(frozen=True)
class SimMessage:
    id: UUID
    kind: str
    text: str
    status: str
    appointment_id: UUID | None
    created_at: datetime


async def messages_for(session: AsyncSession, clinic_id: UUID, phone: str) -> list[SimMessage]:
    """What the clinic sent this caller (replies, approvals, rejections), newest first."""
    rows = await session.scalars(
        select(MessageOutbox)
        .join(BotConversation, BotConversation.id == MessageOutbox.conversation_id)
        .where(
            MessageOutbox.clinic_id == clinic_id,
            BotConversation.channel == CHANNEL,
            BotConversation.phone_e164 == phone,
        )
        .order_by(MessageOutbox.created_at.desc())
        .limit(30)
    )
    return [
        SimMessage(
            id=row.id,
            kind=row.kind,
            text=str(row.body.get("text", "")),
            status=row.status.value,
            appointment_id=row.appointment_id,
            created_at=row.created_at,
        )
        for row in rows
    ]


async def reset(session: AsyncSession, clinic_id: UUID, phone: str) -> None:
    """Forget the simulated caller's conversation (appointments are kept)."""
    await session.execute(
        delete(BotConversation).where(
            BotConversation.clinic_id == clinic_id,
            BotConversation.channel == CHANNEL,
            BotConversation.phone_e164 == phone,
        )
    )
    await session.commit()
