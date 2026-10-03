"""Booking bot: admin status, reception inbox, transcripts, alerts, voice simulator."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import UtcDateTime


class UsageOut(BaseModel):
    month: date
    sent: int
    limit: int
    # Non-essential replies stop here; the rest is kept for essential messages.
    reserve_from: int
    warn: bool  # at or above 80 %
    exhausted: bool


class WhatsAppStatusOut(BaseModel):
    configured: bool
    fake: bool
    connected: bool | None
    display_phone_number: str | None
    verified_name: str | None
    error: str | None
    webhook_url: str | None
    webhook_last_seen_at: UtcDateTime | None
    paid_templates_allowed: bool


class BotStatusOut(BaseModel):
    whatsapp: WhatsAppStatusOut
    usage: UsageOut
    llm_enabled: bool
    stt_provider: str
    tts_provider: str
    clinic_configured: bool


class ConversationSummaryOut(BaseModel):
    id: UUID
    channel: str
    phone: str
    # First names of patients registered with this phone.
    names: list[str]
    language: str | None
    state: str
    handoff_status: str
    handoff_reason: str | None
    handoff_at: UtcDateTime | None
    last_inbound_at: UtcDateTime | None
    last_message: str | None
    # WhatsApp's free 24 h window; outside it reception has to call the patient.
    window_open: bool
    opted_out: bool
    open_alerts: int
    emergency: bool


class TranscriptMessageOut(BaseModel):
    id: UUID
    direction: str
    type: str
    text: str | None
    transcript: str | None
    status: str
    created_at: UtcDateTime


class ConversationDetailOut(ConversationSummaryOut):
    messages: list[TranscriptMessageOut]


class StaffReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class StaffReplyOut(BaseModel):
    # sent | queued | blocked
    status: str


class AppointmentConversationOut(BaseModel):
    conversation_id: UUID | None


class BotAlertOut(BaseModel):
    id: UUID
    kind: str
    conversation_id: UUID
    channel: str
    phone: str
    names: list[str]
    excerpt: str | None
    created_at: UtcDateTime


class KeywordListOut(BaseModel):
    kind: Literal["emergency", "stop", "start"]
    language: Literal["te", "hi", "en"]
    words: list[str]
    custom: bool


class KeywordListIn(BaseModel):
    kind: Literal["emergency", "stop", "start"]
    language: Literal["te", "hi", "en"]
    # null restores the built-in list.
    words: list[Annotated[str, Field(max_length=60)]] | None = Field(default=None, max_length=100)


class SimOptionOut(BaseModel):
    id: str
    title: str
    description: str | None


class SimReplyOut(BaseModel):
    text: str
    options: list[SimOptionOut]


class VoiceTurnOut(BaseModel):
    transcript: str
    # too_long | failed when a recording could not be understood
    voice_error: str | None
    replies: list[SimReplyOut]
    speech_text: str
    # Base64 audio from the TTS provider; null = speak speech_text in the browser.
    audio_base64: str | None
    audio_mime: str | None
    tts_provider: str
    appointment_id: UUID | None
    state: str


class SimMessageOut(BaseModel):
    id: UUID
    kind: str
    text: str
    status: str
    appointment_id: UUID | None
    created_at: UtcDateTime


class SimResetIn(BaseModel):
    phone: str = Field(min_length=5, max_length=20)
