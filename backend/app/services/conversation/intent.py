"""Free text and voice transcripts -> a CLOSED intent schema (suggestions only).

Whatever is parsed only pre-fills the conversation: the patient still picks from lists and
presses Confirm before anything is booked. The LLM never does date arithmetic (it copies the
patient's words; `dates.resolve_date` turns them into a day) and never answers anything.

- `RuleParser`: keyword rules in te/hi/en plus transliterated doctor-name matching. Free and
  deterministic: used when the LLM is off, as the LLM's fallback, and in tests.
- `GroqParser`: the Groq LLM (free tier) through the shared provider factory, JSON only.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Literal, Protocol

import structlog
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.services.conversation.dates import parse_time, resolve_date
from app.services.conversation.keywords import normalize
from app.services.conversation.translit import name_score

if TYPE_CHECKING:
    from app.core.config import Settings

logger = structlog.get_logger(__name__)

IntentName = Literal["book", "cancel", "reschedule", "my_appointments", "reception", "unknown"]
NAME_MATCH = 0.8


class ParsedIntent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent: IntentName = "unknown"
    # Exactly one of the clinic's doctor names, or None.
    doctor: str | None = None
    # The patient's own words for the day / time ("tomorrow", "రేపు", "5 pm").
    date_text: str | None = None
    time_text: str | None = None
    patient_name: str | None = None

    @field_validator("intent", mode="before")
    @classmethod
    def _known(cls, value: Any) -> Any:
        allowed = ("book", "cancel", "reschedule", "my_appointments", "reception")
        return value if value in allowed else "unknown"

    @field_validator("doctor", "date_text", "time_text", "patient_name", mode="before")
    @classmethod
    def _short(cls, value: Any) -> Any:
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip()[:80]


@dataclass(frozen=True)
class IntentRequest:
    text: str
    today: date
    doctors: Sequence[str]
    language: str | None


class Understander(Protocol):
    async def parse(self, request: IntentRequest) -> ParsedIntent: ...


_INTENT_WORDS: tuple[tuple[IntentName, tuple[str, ...]], ...] = (
    (
        "reception",
        (
            "reception",
            "receptionist",
            "talk to",
            "speak to",
            "human",
            "call me",
            "రిసెప్షన్",
            "మనిషితో",
            "రిసెప్शन",
            "रिसेप्शन",
            "किसी से बात",
            "बात करनी",
        ),
    ),
    ("cancel", ("cancel", "రద్దు", "క్యాన్సిల్", "रद्द", "कैंसल")),
    (
        "reschedule",
        (
            "reschedule",
            "change the time",
            "change my appointment",
            "postpone",
            "another time",
            "సమయం మార్చ",
            "మార్చాలి",
            "समय बदल",
            "बदलना",
        ),
    ),
    (
        "my_appointments",
        (
            "my appointment",
            "my booking",
            "when is my",
            "నా అపాయింట్",
            "मेरा अपॉइंटमेंट",
            "मेरे अपॉइंटमेंट",
            "मेरी बुकिंग",
        ),
    ),
    (
        "book",
        (
            "book",
            "appointment",
            "consult",
            "see the doctor",
            "see doctor",
            "అపాయింట్",
            "డాక్టర్",
            "చూపించుకో",
            "बुक",
            "अपॉइंटमेंट",
            "डॉक्टर",
            "दिखाना",
            "मिलना",
        ),
    ),
)


def match_doctor(text: str, doctors: Sequence[str]) -> str | None:
    """The doctor whose (last/first) name the text mentions, in any script."""
    words = [w for w in normalize(text).split() if len(w) >= 3]
    best, best_score = None, 0.0
    for doctor in doctors:
        name_words = [
            w for w in re.split(r"[\s.]+", doctor) if w and w.lower() not in ("dr", "doctor")
        ]
        score = max((name_score(w, n) for w in words for n in name_words), default=0.0)
        if score > best_score:
            best, best_score = doctor, score
    return best if best_score >= NAME_MATCH else None


class RuleParser:
    async def parse(self, request: IntentRequest) -> ParsedIntent:
        text = normalize(request.text)
        intent: IntentName = "unknown"
        for name, words in _INTENT_WORDS:
            if any(normalize(word) in text for word in words):
                intent = name
                break
        doctor = match_doctor(request.text, request.doctors)
        has_date = resolve_date(request.text, request.today) is not None
        has_time = parse_time(request.text) is not None
        if intent == "unknown" and (doctor or has_date):
            intent = "book"
        return ParsedIntent(
            intent=intent,
            doctor=doctor,
            date_text=request.text if has_date else None,
            time_text=request.text if has_time else None,
        )


SYSTEM_PROMPT = """You read one message a patient sent to a clinic's appointment assistant in
India (Telugu, Hindi, English or a mix) and extract what they want. Reply with ONE JSON object
and nothing else:
{"intent": "book" | "cancel" | "reschedule" | "my_appointments" | "reception" | "unknown",
 "doctor": one name copied exactly from DOCTORS, or null,
 "date_text": the patient's own words for the day (e.g. "tomorrow", "రేపు", "कल",
              "next Tuesday", "5 Oct"), or null,
 "time_text": the patient's own words for the time (e.g. "5 pm", "evening 6"), or null,
 "patient_name": the patient's name if they say who the visit is for, or null}
Rules: never calculate dates, copy the words. Never give medical advice or answer questions;
anything that is not about appointments is "unknown". Doctor names may be said in Telugu or
Hindi script (e.g. శర్మ = Sharma)."""


def _json_object(content: str) -> dict[str, Any]:
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the reply")
    data = json.loads(content[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("reply is not an object")
    return data


class GroqParser:
    """The LLM, with the rules as a safety net (errors, rate limits, odd output)."""

    def __init__(self, model: BaseChatModel, fallback: Understander | None = None) -> None:
        self._model = model
        self._fallback = fallback or RuleParser()

    async def parse(self, request: IntentRequest) -> ParsedIntent:
        doctors = "\n".join(f"- {name}" for name in request.doctors) or "- (none)"
        human = (
            f"TODAY: {request.today.isoformat()} ({request.today.strftime('%A')}), IST\n"
            f"DOCTORS:\n{doctors}\n"
            f"MESSAGE: {request.text[:500]}"
        )
        try:
            reply = await self._model.ainvoke([SystemMessage(SYSTEM_PROMPT), HumanMessage(human)])
            parsed = ParsedIntent.model_validate(_json_object(str(reply.content)))
        except (ValueError, ValidationError) as exc:
            logger.info("intent_parse_fallback", error_type=type(exc).__name__)
            return await self._fallback.parse(request)
        except Exception as exc:  # network, rate limit (Groq free tier), ...
            logger.warning("intent_llm_failed", error_type=type(exc).__name__)
            return await self._fallback.parse(request)
        if parsed.doctor not in request.doctors:
            # Only names from the list count; otherwise try the transliterating matcher.
            parsed = parsed.model_copy(
                update={"doctor": match_doctor(request.text, request.doctors)}
            )
        return parsed


def build_understander(settings: "Settings") -> Understander:
    """The Groq LLM when BOT_LLM_ENABLED (and a key is set); otherwise the free rules."""
    from app.services.rag.providers import (  # noqa: PLC0415 - optional LLM stack
        ProviderNotConfiguredError,
        build_chat_model,
    )

    if not settings.bot_llm_enabled or settings.rag_fake_llm:
        return RuleParser()
    try:
        return GroqParser(build_chat_model(settings, "intent"))
    except ProviderNotConfiguredError:
        logger.warning("intent_llm_not_configured")
        return RuleParser()
