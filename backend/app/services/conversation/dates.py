"""Resolve spoken/typed dates and times in Telugu, Hindi and English, relative to today (IST).

The LLM never does date arithmetic: it may return the patient's words ("next Tuesday",
"రేపు", "कल") and this module turns them into a date.

Rules: a bare weekday is the nearest such day from today (today included); "next <weekday>"
is the nearest one after today. In Hindi "कल" means tomorrow here (booking is about the future).
"""

import re
from datetime import date, time, timedelta

from app.services.conversation.keywords import normalize

_RELATIVE: dict[str, int] = {
    "today": 0,
    "tonight": 0,
    "tomorrow": 1,
    "tmrw": 1,
    "day after tomorrow": 2,
    "ఈరోజు": 0,
    "ఇవాళ": 0,
    "ఈ రోజు": 0,
    "రేపు": 1,
    "ఎల్లుండి": 2,
    "आज": 0,
    "कल": 1,
    "परसों": 2,
}

_WEEKDAYS: dict[str, int] = {}
for _index, _names in enumerate(
    (
        ("monday", "mon", "सोमवार", "సోమవారం", "సోమవారము"),
        ("tuesday", "tue", "tues", "मंगलवार", "మంగళవారం", "మంగళవారము"),
        ("wednesday", "wed", "बुधवार", "బుధవారం", "బుధవారము"),
        ("thursday", "thu", "thur", "thurs", "गुरुवार", "బృహస్పతివారం", "గురువారం", "గురువారము"),
        ("friday", "fri", "शुक्रवार", "శుక్రవారం", "శుక్రవారము"),
        ("saturday", "sat", "शनिवार", "శనివారం", "శనివారము"),
        ("sunday", "sun", "रविवार", "ఆదివారం", "ఆదివారము"),
    )
):
    for _name in _names:
        _WEEKDAYS[_name] = _index

_NEXT_WORDS = ("next", "अगले", "अगला", "వచ్చే")

_MONTHS = {
    name: i + 1
    for i, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        )
    )
    for name in names
}

_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b")
_DAY_MONTH = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\b")
_MONTH_DAY = re.compile(r"\b([a-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\b")


def _contains(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def _future(day: int, month: int, year: int | None, today: date) -> date | None:
    try:
        candidate = date(year or today.year, month, day)
    except ValueError:
        return None
    if year is None and candidate < today:
        try:
            candidate = date(today.year + 1, month, day)
        except ValueError:
            return None
    return candidate


def resolve_date(text: str, today: date) -> date | None:
    """The date a patient means, or None if the text names no date."""
    cleaned = normalize(text)
    if not cleaned:
        return None
    # Longest phrases first ("day after tomorrow" before "tomorrow").
    for phrase in sorted(_RELATIVE, key=len, reverse=True):
        if _contains(cleaned, phrase):
            return today + timedelta(days=_RELATIVE[phrase])

    for name, weekday in _WEEKDAYS.items():
        if _contains(cleaned, name):
            ahead = (weekday - today.weekday()) % 7
            wants_next = any(_contains(cleaned, word) for word in _NEXT_WORDS)
            if wants_next and ahead == 0:
                ahead = 7
            return today + timedelta(days=ahead)

    raw = cleaned
    if match := _NUMERIC_DATE.search(text):
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3)) if match.group(3) else None
        if year is not None and year < 100:
            year += 2000
        return _future(day, month, year, today)
    if (match := _DAY_MONTH.search(raw)) and match.group(2) in _MONTHS:
        return _future(int(match.group(1)), _MONTHS[match.group(2)], None, today)
    if (match := _MONTH_DAY.search(raw)) and match.group(1) in _MONTHS:
        return _future(int(match.group(2)), _MONTHS[match.group(1)], None, today)
    return None


# hour, optional :minutes, optional am/pm ("10:30", "5 pm", "5.30pm", "10 a.m.").
_TIME = re.compile(r"(?<![\d/])(\d{1,2})(?:[:.](\d{2}))?\s*(?:([ap])\.?\s?m\b\.?)?(?![\d/])")
_PM_WORDS = ("evening", "afternoon", "night", "शाम", "दोपहर", "రాత్రి", "సాయంత్రం", "మధ్యాహ్నం")
_AM_WORDS = ("morning", "सुबह", "ఉదయం", "పొద్దున")


def parse_time(text: str) -> time | None:
    """A clock time in the text ("10:30", "5 pm", "शाम 5 बजे"), or None."""
    cleaned = text.casefold()
    for match in _TIME.finditer(cleaned):
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        suffix = f"{match.group(3)}m" if match.group(3) else ""
        if match.group(2) is None and not suffix and not _mentions_part_of_day(cleaned):
            # A bare number ("2") is more likely a menu choice than a time.
            continue
        if hour > 23 or minute > 59:
            continue
        if suffix == "pm" or (not suffix and _is_pm(cleaned) and hour < 12):
            hour = hour + 12 if hour < 12 else hour
        elif suffix == "am" and hour == 12:
            hour = 0
        elif not suffix and not _is_am(cleaned) and 1 <= hour <= 7:
            # Clinics don't open at 1-7 AM: "5:30" means 5:30 PM.
            hour += 12
        return time(hour % 24, minute)
    return None


def _mentions_part_of_day(text: str) -> bool:
    return _is_pm(text) or _is_am(text) or "बजे" in text or "గంటలకు" in text


def _is_pm(text: str) -> bool:
    return any(word in text for word in _PM_WORDS)


def _is_am(text: str) -> bool:
    return any(word in text for word in _AM_WORDS)
