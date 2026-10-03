"""Speech-to-text for WhatsApp voice notes and the voice simulator.

- Sarvam (primary): Indian languages and code-mixed speech, REST endpoint up to 30 s.
- Groq Whisper (fallback, free tier): `whisper-large-v3-turbo`.
- Fake (tests / RAG_FAKE_LLM): the "audio" bytes are UTF-8 text.

Audio is only ever held in memory for the call; nothing is written to disk or the database.
"""

from dataclasses import dataclass
from typing import Protocol

import httpx
import structlog

from app.core.config import Settings
from app.services.conversation.types import Language
from app.services.rag.providers import ProviderNotConfiguredError

logger = structlog.get_logger(__name__)

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"
GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_STT_MODEL = "whisper-large-v3-turbo"
MAX_AUDIO_BYTES = 5_000_000
_SARVAM_LANG = {"te": "te-IN", "hi": "hi-IN", "en": "en-IN"}


class TranscriptionError(Exception):
    """The audio could not be transcribed. `too_long` asks the patient for a shorter note."""

    def __init__(self, message: str, *, too_long: bool = False) -> None:
        super().__init__(message)
        self.too_long = too_long


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None = None
    provider: str = ""


class SpeechToText(Protocol):
    async def transcribe(
        self, audio: bytes, mime_type: str, language: Language | None
    ) -> Transcript: ...


def _filename(mime_type: str) -> str:
    base = mime_type.split(";", maxsplit=1)[0].strip().lower()
    extension = {
        "audio/ogg": "ogg",
        "audio/opus": "opus",
        "audio/webm": "webm",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
        "audio/aac": "aac",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/amr": "amr",
    }.get(base, "ogg")
    return f"audio.{extension}"


def _upload(audio: bytes, mime_type: str) -> tuple[str, bytes, str]:
    return _filename(mime_type), audio, mime_type.split(";", maxsplit=1)[0]


def _check_size(audio: bytes) -> None:
    if not audio:
        raise TranscriptionError("empty audio")
    if len(audio) > MAX_AUDIO_BYTES:
        raise TranscriptionError("audio too large", too_long=True)


class SarvamSTT:
    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        self._key = api_key
        self._timeout = timeout

    async def transcribe(
        self, audio: bytes, mime_type: str, language: Language | None
    ) -> Transcript:
        _check_size(audio)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    SARVAM_STT_URL,
                    headers={"api-subscription-key": self._key},
                    files={"file": _upload(audio, mime_type)},
                    data={"language_code": _SARVAM_LANG.get(language or "", "unknown")},
                )
        except httpx.HTTPError as exc:
            raise TranscriptionError(f"sarvam: {type(exc).__name__}") from exc
        if response.status_code != 200:
            detail = response.text[:300].lower()
            too_long = "duration" in detail or "too long" in detail or "30 seconds" in detail
            raise TranscriptionError(f"sarvam: HTTP {response.status_code}", too_long=too_long)
        body = response.json()
        return Transcript(
            text=str(body.get("transcript", "")).strip(),
            language=body.get("language_code"),
            provider="sarvam",
        )


class GroqWhisperSTT:
    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        self._key = api_key
        self._timeout = timeout

    async def transcribe(
        self, audio: bytes, mime_type: str, language: Language | None
    ) -> Transcript:
        _check_size(audio)
        data = {"model": GROQ_STT_MODEL, "response_format": "json", "temperature": "0"}
        if language:
            data["language"] = language
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    GROQ_STT_URL,
                    headers={"Authorization": f"Bearer {self._key}"},
                    files={"file": _upload(audio, mime_type)},
                    data=data,
                )
        except httpx.HTTPError as exc:
            raise TranscriptionError(f"groq: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise TranscriptionError(f"groq: HTTP {response.status_code}")
        return Transcript(text=str(response.json().get("text", "")).strip(), provider="groq")


class FallbackSTT:
    """Try each provider in turn; a "too long" error is final (another won't help)."""

    def __init__(self, *providers: SpeechToText) -> None:
        self._providers = providers

    async def transcribe(
        self, audio: bytes, mime_type: str, language: Language | None
    ) -> Transcript:
        last: TranscriptionError | None = None
        for provider in self._providers:
            try:
                return await provider.transcribe(audio, mime_type, language)
            except TranscriptionError as exc:
                logger.warning(
                    "stt_failed", provider=type(provider).__name__, too_long=exc.too_long
                )
                if exc.too_long:
                    raise
                last = exc
        raise last or TranscriptionError("no speech-to-text provider")


class FakeSTT:
    """Tests and E2E: the audio bytes are the transcript (UTF-8)."""

    async def transcribe(
        self, audio: bytes, mime_type: str, language: Language | None
    ) -> Transcript:
        _check_size(audio)
        try:
            text = audio.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise TranscriptionError("fake stt: not text") from exc
        if text == "TOO_LONG":
            raise TranscriptionError("fake stt: too long", too_long=True)
        return Transcript(text=text, language=language, provider="fake")


def _secret(value: object) -> str | None:
    if value is None:
        return None
    secret = str(value.get_secret_value()).strip()  # type: ignore[attr-defined]
    return secret or None


def build_stt(settings: Settings) -> SpeechToText:
    """The configured provider chain. Raises ProviderNotConfiguredError when nothing works."""
    if settings.stt_provider == "fake" or settings.rag_fake_llm:
        return FakeSTT()
    sarvam_key, groq_key = _secret(settings.sarvam_api_key), _secret(settings.groq_api_key)
    chain: list[SpeechToText] = []
    if settings.stt_provider == "sarvam" and sarvam_key:
        chain.append(SarvamSTT(sarvam_key))
    if groq_key:
        chain.append(GroqWhisperSTT(groq_key))
    if settings.stt_provider == "groq" and sarvam_key:
        chain.append(SarvamSTT(sarvam_key))
    if not chain:
        raise ProviderNotConfiguredError("No speech-to-text key (SARVAM_API_KEY or GROQ_API_KEY)")
    return chain[0] if len(chain) == 1 else FallbackSTT(*chain)
