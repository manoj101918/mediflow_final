"""Stored WhatsApp messages -> the engine's InboundMsg (voice notes go through speech-to-text).

A voice note is downloaded from Meta, transcribed, and only the transcript is kept
(channel_messages.transcript). The audio lives in memory for the duration of the call and is
never written to disk or the database.
"""

from collections.abc import Awaitable, Callable
from typing import Protocol

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import BotConversation, ChannelMessage
from app.services.conversation import InboundMsg
from app.services.conversation.types import LANGUAGES, Language, VoiceError
from app.services.messaging.dispatch import SendError
from app.services.rag.providers import ProviderNotConfiguredError
from app.services.speech.stt import SpeechToText, TranscriptionError, build_stt
from app.services.whatsapp.parse import IncomingMessage, message_from_raw

logger = structlog.get_logger(__name__)

Normalizer = Callable[[AsyncSession, ChannelMessage], Awaitable[InboundMsg]]


class MediaSource(Protocol):
    async def download(self, media_id: str) -> tuple[bytes, str]: ...


def to_inbound(
    message: ChannelMessage,
    parsed: IncomingMessage,
    text: str | None = None,
    *,
    voice_error: VoiceError | None = None,
) -> InboundMsg:
    return InboundMsg(
        channel=message.channel,
        phone_e164=message.phone_e164,
        kind=parsed.kind,  # type: ignore[arg-type]
        text=parsed.text if text is None else text,
        reply_id=parsed.reply_id,
        message_id=message.id,
        external_id=message.wamid,
        sent_at=parsed.sent_at,
        voice_error=voice_error,
    )


def _parse(message: ChannelMessage) -> IncomingMessage:
    parsed = message_from_raw(message.payload)
    if parsed is None:
        raise ValueError("stored message cannot be parsed")
    return parsed


async def plain_normalizer(_: AsyncSession, message: ChannelMessage) -> InboundMsg:
    """Text and interactive replies as they are; voice notes arrive without a transcript."""
    parsed = _parse(message)
    error: VoiceError | None = "failed" if parsed.kind == "voice" else None
    return to_inbound(message, parsed, voice_error=error)


async def _language(session: AsyncSession, message: ChannelMessage) -> Language | None:
    value = await session.scalar(
        select(BotConversation.language).where(
            BotConversation.clinic_id == message.clinic_id,
            BotConversation.channel == message.channel,
            BotConversation.phone_e164 == message.phone_e164,
        )
    )
    return next((code for code in LANGUAGES if code == value), None)


def voice_normalizer(media: MediaSource | None, stt: SpeechToText | None) -> Normalizer:
    async def normalize(session: AsyncSession, message: ChannelMessage) -> InboundMsg:
        parsed = _parse(message)
        if parsed.kind != "voice":
            return to_inbound(message, parsed)
        if media is None or stt is None or parsed.media_id is None:
            return to_inbound(message, parsed, "", voice_error="failed")
        language = await _language(session, message)
        try:
            audio, mime_type = await media.download(parsed.media_id)
            transcript = await stt.transcribe(audio, mime_type or "audio/ogg", language)
            del audio  # never kept: only the transcript is stored
        except TranscriptionError as exc:
            error: VoiceError = "too_long" if exc.too_long else "failed"
            return to_inbound(message, parsed, "", voice_error=error)
        except SendError:
            return to_inbound(message, parsed, "", voice_error="failed")
        if not transcript.text:
            return to_inbound(message, parsed, "", voice_error="failed")
        await session.execute(
            update(ChannelMessage)
            .where(ChannelMessage.id == message.id)
            .values(transcript=transcript.text[:2000], body_text=transcript.text[:2000])
        )
        await session.commit()
        logger.info(
            "voice_note_transcribed", message_id=str(message.id), provider=transcript.provider
        )
        return to_inbound(message, parsed, transcript.text)

    return normalize


def build_normalizer(settings: Settings) -> Normalizer:
    from app.services.whatsapp.client import build_sender  # noqa: PLC0415 - avoids a cycle

    sender = build_sender(settings)
    media: MediaSource | None = sender if hasattr(sender, "download") else None  # type: ignore[assignment]
    try:
        stt: SpeechToText | None = build_stt(settings)
    except ProviderNotConfiguredError:
        logger.warning("voice_notes_disabled", reason="no speech-to-text key")
        stt = None
    return voice_normalizer(media, stt)
