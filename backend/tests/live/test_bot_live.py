"""Live checks of the booking bot's external services (Meta, Sarvam, Groq).

    cd backend
    uv run python -m pytest -m live -s tests/live/test_bot_live.py

Each test skips unless its keys are in backend/.env. Costs: the WhatsApp send uses one of
Meta's 1,000 free monthly service messages (and needs LIVE_WHATSAPP_TO: a test recipient that
messaged the business number within the last 24 hours); Sarvam uses a few paise of signup
credit; Groq stays on the free tier.
"""

import os
from datetime import timedelta

import pytest

from app.core.config import get_settings
from app.services.booking.timeutil import clinic_tz, today_local
from app.services.conversation.dates import resolve_date
from app.services.conversation.intent import GroqParser, IntentRequest
from app.services.rag.providers import ProviderNotConfiguredError, build_chat_model
from app.services.speech.stt import GroqWhisperSTT, SarvamSTT
from app.services.speech.tts import SarvamTTS
from app.services.whatsapp.client import PyWaSender, check_connection

pytestmark = pytest.mark.live

TELUGU = "రేపు డాక్టర్ శర్మ దగ్గర అపాయింట్‌మెంట్ కావాలి"
DOCTORS = ["Dr. Anil Sharma", "Dr. Lakshmi Iyer", "Dr. Imran Khan"]


def _secret(name: str) -> str:
    value = getattr(get_settings(), name)
    secret = value.get_secret_value().strip() if value is not None else ""
    if not secret:
        pytest.skip(f"{name.upper()} is not set")
    return secret


async def test_whatsapp_number_is_reachable() -> None:
    settings = get_settings()
    _secret("whatsapp_access_token")
    info = await check_connection(settings)
    assert info is not None and info.connected, info
    print(f"\nWhatsApp: {info.display_phone_number} ({info.verified_name})")


async def test_whatsapp_free_form_message_reaches_the_test_recipient() -> None:
    settings = get_settings()
    token = _secret("whatsapp_access_token")
    to = os.environ.get("LIVE_WHATSAPP_TO", "").strip()
    if not to or not settings.whatsapp_phone_number_id:
        pytest.skip("Set LIVE_WHATSAPP_TO (+91..., messaged the business number < 24 h ago)")
    sender = PyWaSender(settings.whatsapp_phone_number_id, token, settings.whatsapp_api_version)
    wamid = await sender.send(
        to,
        {
            "text": "MediFlow live test: please ignore.",
            "buttons": [{"id": "live:ok", "title": "OK"}],
        },
    )
    assert wamid.startswith("wamid.")


async def test_sarvam_speaks_and_understands_telugu() -> None:
    key = _secret("sarvam_api_key")
    speech = await SarvamTTS(key).synthesize(TELUGU, "te")
    assert speech.provider == "sarvam" and speech.audio
    transcript = await SarvamSTT(key).transcribe(speech.audio, "audio/mpeg", "te")
    print(f"\nSarvam transcript: {transcript.text}")
    assert "రేపు" in transcript.text


async def test_groq_whisper_fallback_transcribes() -> None:
    sarvam, groq = _secret("sarvam_api_key"), _secret("groq_api_key")
    speech = await SarvamTTS(sarvam).synthesize("I want an appointment tomorrow", "en")
    assert speech.audio
    transcript = await GroqWhisperSTT(groq).transcribe(speech.audio, "audio/mpeg", "en")
    print(f"\nWhisper transcript: {transcript.text}")
    assert "appointment" in transcript.text.lower()


async def test_groq_extracts_the_telugu_booking_intent() -> None:
    _secret("groq_api_key")
    try:
        model = build_chat_model(
            get_settings().model_copy(update={"rag_fake_llm": False}), "intent"
        )
    except ProviderNotConfiguredError:
        pytest.skip("GROQ_API_KEY is not set")
    today = today_local(clinic_tz())
    parsed = await GroqParser(model).parse(
        IntentRequest(text=TELUGU, today=today, doctors=DOCTORS, language="te")
    )
    print(f"\nGroq: {parsed}")
    assert parsed.intent == "book"
    assert parsed.doctor == "Dr. Anil Sharma"
    assert parsed.date_text is not None
    assert resolve_date(parsed.date_text, today) == today + timedelta(days=1)
