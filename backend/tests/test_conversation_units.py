"""Pure helpers of the conversation engine: dates, times, keywords, option matching, i18n."""

from datetime import date, time

import pytest

from app.db.models import BotChannel
from app.services.conversation.dates import parse_time, resolve_date
from app.services.conversation.i18n import CATALOG, LANGUAGE_TITLES, REASONS, t
from app.services.conversation.keywords import build_keywords, is_medical_question
from app.services.conversation.options import match_option
from app.services.conversation.types import (
    BUTTON_TITLE_MAX,
    LANGUAGES,
    ROW_TITLE_MAX,
    InboundMsg,
    Option,
)

THURSDAY = date(2026, 10, 1)  # a Thursday


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("today", THURSDAY),
        ("tomorrow please", date(2026, 10, 2)),
        ("day after tomorrow", date(2026, 10, 3)),
        ("రేపు డాక్టర్ శర్మ దగ్గర అపాయింట్‌మెంట్ కావాలి", date(2026, 10, 2)),
        ("ఎల్లుండి", date(2026, 10, 3)),
        ("कल सुबह", date(2026, 10, 2)),
        ("परसों", date(2026, 10, 3)),
        ("thursday", THURSDAY),
        ("next thursday", date(2026, 10, 8)),
        ("tuesday", date(2026, 10, 6)),
        ("अगले सोमवार", date(2026, 10, 5)),
        ("శనివారం", date(2026, 10, 3)),
        ("5/10", date(2026, 10, 5)),
        ("12 oct", date(2026, 10, 12)),
        ("Oct 3rd", date(2026, 10, 3)),
        ("2 jan", date(2027, 1, 2)),
        ("book an appointment", None),
    ],
)
def test_resolve_date(text: str, expected: date | None) -> None:
    assert resolve_date(text, THURSDAY) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10:30", time(10, 30)),
        ("5 pm", time(17, 0)),
        ("5.30pm", time(17, 30)),
        ("10 a.m.", time(10, 0)),
        ("12 pm", time(12, 0)),
        ("शाम 5 बजे", time(17, 0)),
        ("సాయంత్రం 6 గంటలకు", time(18, 0)),
        ("ఉదయం 9", time(9, 0)),
        ("4:15", time(16, 15)),
        ("2", None),
        ("on 5/10", None),
    ],
)
def test_parse_time(text: str, expected: time | None) -> None:
    assert parse_time(text) == expected


def test_keywords_cover_all_languages_and_overrides() -> None:
    words = build_keywords()
    assert words.is_stop("STOP") and words.is_stop("ఆపండి") and words.is_stop("बंद करो!")
    assert not words.is_stop("please stop the appointment reminders now")
    assert words.is_start("Start") and words.is_start("शुरू")
    assert words.is_emergency("He has CHEST PAIN") and words.is_emergency("గుండెపోటు వచ్చింది")
    assert not words.is_emergency("I want to book an appointment")

    custom = build_keywords({("emergency", "en"): ["collapsed"]})
    assert custom.is_emergency("my wife collapsed")
    assert not custom.is_emergency("chest pain")  # English list replaced
    assert custom.is_emergency("బేహోష్ గుండెపోటు")  # Telugu defaults kept


@pytest.mark.parametrize(
    ("text", "medical"),
    [
        ("what is the dosage of paracetamol", True),
        ("is it serious?", True),
        ("can I take 500 mg", True),
        ("मुझे कौन सी दवाई लेनी चाहिए", True),
        ("ఈ మాత్ర వేసుకోవచ్చా", True),
        ("I want an appointment for fever", False),
        ("Ravi Kumar", False),
    ],
)
def test_medical_questions(text: str, medical: bool) -> None:
    assert is_medical_question(text) is medical


OPTIONS = [
    Option("d:1", "Dr. Anil Sharma", "General Physician"),
    Option("d:2", "Dr. Lakshmi Iyer", "Pediatrician"),
    Option("d:3", "Dr. Imran Khan", "Orthopedics"),
]


def _msg(text: str = "", reply_id: str | None = None) -> InboundMsg:
    return InboundMsg(
        channel=BotChannel.WHATSAPP,
        phone_e164="+919800000001",
        kind="reply" if reply_id else "text",
        text=text,
        reply_id=reply_id,
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2", "d:2"),
        ("two", "d:2"),
        ("రెండు", "d:2"),
        ("तीन", "d:3"),
        ("Dr. Imran Khan", "d:3"),
        ("doctor sharma please", "d:1"),
        ("Lakshmi Iyer", "d:2"),
        ("7", None),
        ("someone", None),
    ],
)
def test_match_option_from_text(text: str, expected: str | None) -> None:
    match = match_option(_msg(text), OPTIONS)
    assert (match.id if match else None) == expected


def test_match_option_from_reply_id_only_when_offered() -> None:
    assert match_option(_msg(reply_id="d:1"), OPTIONS) == OPTIONS[0]
    assert match_option(_msg(reply_id="d:9"), OPTIONS) is None


def test_titles_fit_whatsapp_limits() -> None:
    for key, texts in CATALOG.items():
        for language in LANGUAGES:
            if key.startswith("btn_"):
                assert len(texts[language]) <= BUTTON_TITLE_MAX, (key, language)
            if key.startswith(("reason_", "row_", "list_")):
                assert len(texts[language]) <= ROW_TITLE_MAX, (key, language)
    assert all(len(title) <= BUTTON_TITLE_MAX for title in LANGUAGE_TITLES.values())
    assert len(REASONS) + 1 <= 10  # reasons + skip fit one list


def test_every_string_exists_in_every_language() -> None:
    for key, texts in CATALOG.items():
        assert set(texts) == set(LANGUAGES), key
    assert "{doctor}" in t("te", "date", doctor="{doctor}")
