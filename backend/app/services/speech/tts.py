"""Text-to-speech for the voice simulator (and later the phone line).

- Sarvam Bulbul: natural Telugu / Hindi / English voices from native-script text.
- Browser (free, default): no audio is produced; the page speaks with `speechSynthesis`.
- Fake (tests): a tiny deterministic payload.
"""

import base64
from dataclasses import dataclass
from typing import Protocol

import httpx
import structlog

from app.core.config import Settings
from app.services.conversation.types import Language
from app.services.rag.providers import ProviderNotConfiguredError

logger = structlog.get_logger(__name__)

SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
SARVAM_TTS_MODEL = "bulbul:v2"  # half the price of v3; native-script input
SARVAM_SPEAKER = "anushka"
SARVAM_MAX_CHARS = 1500
_LANG = {"te": "te-IN", "hi": "hi-IN", "en": "en-IN"}


@dataclass(frozen=True)
class Speech:
    """Synthesized audio, or None when the browser should speak the text itself."""

    audio: bytes | None
    mime_type: str | None
    provider: str


class TextToSpeech(Protocol):
    async def synthesize(self, text: str, language: Language) -> Speech: ...


class BrowserTTS:
    async def synthesize(self, text: str, language: Language) -> Speech:
        return Speech(audio=None, mime_type=None, provider="browser")


class FakeTTS:
    async def synthesize(self, text: str, language: Language) -> Speech:
        return Speech(audio=f"{language}:{text}".encode(), mime_type="text/plain", provider="fake")


class SarvamTTS:
    def __init__(self, api_key: str, timeout: float = 20.0) -> None:
        self._key = api_key
        self._timeout = timeout

    async def synthesize(self, text: str, language: Language) -> Speech:
        body = {
            "text": text[:SARVAM_MAX_CHARS],
            "language_code": _LANG[language],
            "model": SARVAM_TTS_MODEL,
            "speaker": SARVAM_SPEAKER,
            "output_audio_codec": "mp3",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    SARVAM_TTS_URL, headers={"api-subscription-key": self._key}, json=body
                )
            response.raise_for_status()
            audios = response.json().get("audios") or []
            audio = base64.b64decode("".join(audios)) if audios else b""
        except (httpx.HTTPError, ValueError) as exc:
            # The browser's voice is a free fallback; the conversation goes on.
            logger.warning("tts_failed", provider="sarvam", error_type=type(exc).__name__)
            return Speech(audio=None, mime_type=None, provider="browser")
        if not audio:
            return Speech(audio=None, mime_type=None, provider="browser")
        return Speech(audio=audio, mime_type="audio/mpeg", provider="sarvam")


def build_tts(settings: Settings) -> TextToSpeech:
    if settings.tts_provider == "fake" or settings.rag_fake_llm:
        return FakeTTS()
    if settings.tts_provider == "sarvam":
        secret = settings.sarvam_api_key
        key = secret.get_secret_value().strip() if secret is not None else ""
        if not key:
            raise ProviderNotConfiguredError("SARVAM_API_KEY is not set")
        return SarvamTTS(key)
    return BrowserTTS()
