"""Safety keywords: opt-out/opt-in words, emergencies and medical-advice questions.

Patients code-mix, so every language's list is checked whatever language was chosen.
STOP/START must be the whole message; emergency and medical words match anywhere.
Clinics can override the STOP/START/emergency lists per language (bot_keyword_lists).
"""

import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BotKeywordList
from app.services.conversation.types import LANGUAGES, Language

KeywordKind = str  # 'stop' | 'start' | 'emergency'
KEYWORD_KINDS = ("emergency", "stop", "start")

DEFAULT_KEYWORDS: dict[str, dict[Language, tuple[str, ...]]] = {
    "stop": {
        "en": ("stop", "unsubscribe", "opt out", "optout", "stop messages"),
        "hi": ("बंद", "बंद करो", "बंद करें", "रोको", "मैसेज बंद", "स्टॉप"),
        "te": ("ఆపు", "ఆపండి", "ఆపేయండి", "మెసేజ్ ఆపండి", "స్టాప్"),
    },
    "start": {
        "en": ("start", "subscribe", "unstop"),
        "hi": ("शुरू", "शुरू करो", "शुरू करें", "स्टार्ट"),
        "te": ("ప్రారంభం", "ప్రారంభించు", "మొదలుపెట్టు", "స్టార్ట్"),
    },
    "emergency": {
        "en": (
            "emergency",
            "chest pain",
            "can't breathe",
            "cannot breathe",
            "not breathing",
            "unconscious",
            "fainted",
            "heavy bleeding",
            "heart attack",
            "stroke",
            "seizure",
            "suicide",
            "kill myself",
            "poison",
            "accident",
            "snake bite",
        ),
        "hi": (
            "आपातकाल",
            "इमरजेंसी",
            "सीने में दर्द",
            "छाती में दर्द",
            "सांस नहीं",
            "साँस नहीं",
            "बेहोश",
            "बहुत खून",
            "दिल का दौरा",
            "लकवा",
            "जहर",
            "ज़हर",
            "आत्महत्या",
            "एक्सीडेंट",
            "सांप ने काटा",
        ),
        "te": (
            "అత్యవసరం",
            "ఎమర్జెన్సీ",
            "ఛాతీ నొప్పి",
            "గుండె నొప్పి",
            "ఊపిరి ఆడటం లేదు",
            "శ్వాస ఆడటం లేదు",
            "స్పృహ లేదు",
            "స్పృహ తప్పి",
            "చాలా రక్తం",
            "గుండెపోటు",
            "పక్షవాతం",
            "విషం",
            "ఆత్మహత్య",
            "యాక్సిడెంట్",
            "పాము కాటు",
        ),
    },
}

# Questions asking for diagnosis, dosage or how serious something is. Not configurable.
MEDICAL_WORDS = frozenset(
    {"dose", "dosage", "mg", "tablet", "tablets", "medicine", "medicines", "drug", "diagnosis"}
)
MEDICAL_PHRASES = (
    "side effect",
    "is it serious",
    "is this serious",
    "should i take",
    "can i take",
    "what to take",
    "what should i take",
    "treatment for",
    "cure for",
    "home remedy",
    "दवा",
    "दवाई",
    "गोली",
    "खुराक",
    "डोज़",
    "गंभीर है",
    "इलाज",
    "మందు",
    "మాత్ర",
    "డోస్",
    "తీవ్రమా",
    "ప్రమాదమా",
    "చికిత్స",
    "వేసుకోవాలా",
)

_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """NFC, lower case, punctuation removed (combining marks kept), single spaces."""
    cleaned = unicodedata.normalize("NFC", text).casefold()
    # \w drops Indic vowel signs (category Mn/Mc), so keep marks explicitly.
    kept = "".join(
        ch
        if (ch.isalnum() or ch.isspace() or ch == "'" or unicodedata.category(ch)[0] == "M")
        else " "
        for ch in cleaned
    )
    return _SPACES.sub(" ", kept).strip()


@dataclass(frozen=True)
class KeywordSet:
    stop: frozenset[str]
    start: frozenset[str]
    emergency: tuple[str, ...]

    def is_stop(self, text: str) -> bool:
        return normalize(text) in self.stop

    def is_start(self, text: str) -> bool:
        return normalize(text) in self.start

    def is_emergency(self, text: str) -> bool:
        cleaned = normalize(text)
        return bool(cleaned) and any(word in cleaned for word in self.emergency)


def build_keywords(overrides: dict[tuple[str, Language], list[str]] | None = None) -> KeywordSet:
    lists: dict[str, list[str]] = {kind: [] for kind in KEYWORD_KINDS}
    for kind in KEYWORD_KINDS:
        for lang in LANGUAGES:
            words = (overrides or {}).get((kind, lang))
            source = words if words is not None else DEFAULT_KEYWORDS[kind][lang]
            lists[kind].extend(n for w in source if (n := normalize(w)))
    return KeywordSet(
        stop=frozenset(lists["stop"]),
        start=frozenset(lists["start"]),
        emergency=tuple(dict.fromkeys(lists["emergency"])),
    )


async def load_keywords(session: AsyncSession, clinic_id: UUID) -> KeywordSet:
    rows = await session.scalars(
        select(BotKeywordList).where(BotKeywordList.clinic_id == clinic_id)
    )
    overrides: dict[tuple[str, Language], list[str]] = {}
    for row in rows:
        if row.language in LANGUAGES:
            overrides[(row.kind, row.language)] = list(row.words)
    return build_keywords(overrides)


def is_medical_question(text: str) -> bool:
    cleaned = normalize(text)
    if not cleaned:
        return False
    if MEDICAL_WORDS.intersection(cleaned.split()):
        return True
    return any(phrase in cleaned for phrase in MEDICAL_PHRASES)


@dataclass(frozen=True)
class KeywordList:
    kind: str
    language: Language
    words: list[str]
    custom: bool  # False = the built-in defaults


async def keyword_lists(session: AsyncSession, clinic_id: UUID) -> list[KeywordList]:
    """Every editable list (emergency/stop/start x te/hi/en), custom or default."""
    rows = await session.scalars(
        select(BotKeywordList).where(BotKeywordList.clinic_id == clinic_id)
    )
    custom = {(row.kind, row.language): list(row.words) for row in rows}
    return [
        KeywordList(
            kind=kind,
            language=lang,
            words=custom.get((kind, lang), list(DEFAULT_KEYWORDS[kind][lang])),
            custom=(kind, lang) in custom,
        )
        for kind in KEYWORD_KINDS
        for lang in LANGUAGES
    ]


def clean_words(words: list[str]) -> list[str]:
    """Trimmed, de-duplicated, non-empty words (max 100, each up to 60 characters)."""
    seen: dict[str, str] = {}
    for word in words:
        value = " ".join(word.split())[:60]
        if value and normalize(value) and normalize(value) not in seen:
            seen[normalize(value)] = value
    return list(seen.values())[:100]


async def save_keyword_list(
    session: AsyncSession,
    clinic_id: UUID,
    kind: str,
    language: Language,
    words: list[str] | None,
    user_id: UUID,
) -> None:
    """Replace a list; None restores the built-in defaults."""

    if words is None:
        await session.execute(
            delete(BotKeywordList).where(
                BotKeywordList.clinic_id == clinic_id,
                BotKeywordList.kind == kind,
                BotKeywordList.language == language,
            )
        )
    else:
        values = {"words": clean_words(words), "updated_by": user_id}
        await session.execute(
            insert(BotKeywordList)
            .values(clinic_id=clinic_id, kind=kind, language=language, **values)
            .on_conflict_do_update(index_elements=["clinic_id", "kind", "language"], set_=values)
        )
    await session.commit()
