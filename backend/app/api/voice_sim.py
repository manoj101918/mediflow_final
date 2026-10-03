"""Admin: the voice booking simulator (push-to-talk in the browser -> STT -> bot -> TTS)."""

import base64
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, Query, UploadFile, status

from app.core.config import get_settings
from app.core.errors import AppError
from app.deps import AdminUser, BotDispatch, DbSession
from app.schemas.bot import (
    SimMessageOut,
    SimOptionOut,
    SimReplyOut,
    SimResetIn,
    VoiceTurnOut,
)
from app.services import voice_sim
from app.services.booking import normalize_phone
from app.services.conversation.intent import build_understander
from app.services.messaging.dispatch import DispatchDeps
from app.services.rag.providers import ProviderNotConfiguredError
from app.services.speech.stt import SpeechToText, build_stt
from app.services.speech.tts import TextToSpeech, build_tts

router = APIRouter(prefix="/admin/voice-sim", tags=["admin"])

MAX_AUDIO_BYTES = 2_000_000  # ~1 minute of browser opus; Sarvam's REST limit is 30 s


class SpeechProviders:
    def __init__(self, stt: SpeechToText | None, tts: TextToSpeech) -> None:
        self.stt, self.tts = stt, tts


def get_speech_providers() -> SpeechProviders:
    """STT (None when no key) and TTS from settings. Tests override this."""
    settings = get_settings()
    try:
        stt: SpeechToText | None = build_stt(settings)
    except ProviderNotConfiguredError:
        stt = None
    try:
        tts = build_tts(settings)
    except ProviderNotConfiguredError as exc:
        raise AppError(503, "NOT_CONFIGURED", str(exc)) from exc
    return SpeechProviders(stt, tts)


Speech = Annotated[SpeechProviders, Depends(get_speech_providers)]


def _phone(raw: str) -> str:
    phone = normalize_phone(raw)
    if phone is None:
        raise AppError(422, "VALIDATION", "Enter a valid test phone number.")
    return phone


def _deps(speech: SpeechProviders, dispatch: DispatchDeps) -> voice_sim.VoiceDeps:
    settings = get_settings()
    return voice_sim.VoiceDeps(
        stt=speech.stt,
        tts=speech.tts,
        understand=build_understander(settings),
        dispatch=dispatch,
        notice_version=settings.bot_notice_version,
    )


@router.post("/turn")
async def turn(
    session: DbSession,
    user: AdminUser,
    speech: Speech,
    dispatch: BotDispatch,
    phone: Annotated[str, Form(min_length=5, max_length=20)],
    language: Annotated[Literal["te", "hi", "en"], Form()],
    text: Annotated[str | None, Form(max_length=500)] = None,
    reply_id: Annotated[str | None, Form(max_length=200)] = None,
    audio: UploadFile | None = None,
) -> VoiceTurnOut:
    """One caller utterance: a recording, typed text, or a tapped option."""
    data: bytes | None = None
    if audio is not None:
        data = await audio.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            raise AppError(
                413, "FILE_TOO_LARGE", "Recording is too long; keep it under 30 seconds."
            )
    elif not (text and text.strip()) and not reply_id:
        raise AppError(422, "VALIDATION", "Send a recording, text or an option.")
    spoken = await voice_sim.take_turn(
        session,
        user.clinic_id,
        _deps(speech, dispatch),
        phone=_phone(phone),
        language=language,
        text=text,
        reply_id=reply_id,
        audio=data,
        mime_type=(audio.content_type if audio is not None else None) or "audio/webm",
    )
    return VoiceTurnOut(
        transcript=spoken.transcript,
        voice_error=spoken.voice_error,
        replies=[
            SimReplyOut(
                text=r.text,
                options=[
                    SimOptionOut(id=o.id, title=o.title, description=o.description)
                    for o in (*r.buttons, *r.rows)
                ],
            )
            for r in spoken.replies
        ],
        speech_text=spoken.speech_text,
        audio_base64=base64.b64encode(spoken.speech.audio).decode()
        if spoken.speech.audio and (spoken.speech.mime_type or "").startswith("audio/")
        else None,
        audio_mime=spoken.speech.mime_type,
        tts_provider=spoken.speech.provider,
        appointment_id=spoken.appointment_id,
        state=spoken.state,
    )


@router.get("/messages")
async def messages(
    session: DbSession, user: AdminUser, phone: Annotated[str, Query(min_length=5, max_length=20)]
) -> list[SimMessageOut]:
    """Everything the clinic sent this simulated caller, including approval messages."""
    rows = await voice_sim.messages_for(session, user.clinic_id, _phone(phone))
    return [
        SimMessageOut(
            id=m.id,
            kind=m.kind,
            text=m.text,
            status=m.status,
            appointment_id=m.appointment_id,
            created_at=m.created_at,
        )
        for m in rows
    ]


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset(body: SimResetIn, session: DbSession, user: AdminUser) -> None:
    await voice_sim.reset(session, user.clinic_id, _phone(body.phone))
