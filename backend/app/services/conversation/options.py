"""Match a patient's answer against the options the bot last offered.

Button/list replies carry the option id. Typed or spoken answers may be the option's number
("2", "two", "రెండు", "दो"), its title, or a sentence containing the title
("Doctor Sharma please"). Only a unique match counts.
"""

from collections.abc import Sequence
from typing import Any

from app.services.conversation.keywords import normalize
from app.services.conversation.types import InboundMsg, Option

NUMBER_WORDS: dict[str, int] = {}
for _value, _words in enumerate(
    (
        ("one", "first", "ఒకటి", "ఒకటో", "మొదటి", "एक", "पहला", "पहले"),
        ("two", "second", "రెండు", "రెండో", "दो", "दूसरा"),
        ("three", "third", "మూడు", "మూడో", "तीन", "तीसरा"),
        ("four", "fourth", "నాలుగు", "चार", "चौथा"),
        ("five", "fifth", "ఐదు", "पांच", "पाँच"),
        ("six", "ఆరు", "छह", "छः"),
        ("seven", "ఏడు", "सात"),
        ("eight", "ఎనిమిది", "आठ"),
        ("nine", "తొమ్మిది", "नौ"),
        ("ten", "పది", "दस"),
    ),
    start=1,
):
    for _word in _words:
        NUMBER_WORDS[_word] = _value

_FILLER = frozenset({"dr", "doctor", "డాక్టర్", "डॉक्टर", "please", "number", "option", "no"})


def options_from_draft(draft: dict[str, Any]) -> list[Option]:
    return [
        Option(id=str(o["id"]), title=str(o["title"]), description=o.get("description"))
        for o in draft.get("options", [])
    ]


def options_to_draft(options: Sequence[Option]) -> list[dict[str, Any]]:
    return [{"id": o.id, "title": o.title, "description": o.description} for o in options]


def _number(text: str) -> int | None:
    if text.isdigit():
        return int(text)
    words = [w for w in text.split() if w not in _FILLER]
    if len(words) == 1:
        word = words[0]
        if word.isdigit():
            return int(word)
        return NUMBER_WORDS.get(word)
    return None


def match_option(msg: InboundMsg, options: Sequence[Option]) -> Option | None:
    if not options:
        return None
    if msg.reply_id is not None:
        return next((o for o in options if o.id == msg.reply_id), None)

    text = normalize(msg.text)
    if not text:
        return None
    number = _number(text)
    if number is not None and 1 <= number <= len(options):
        return options[number - 1]

    titles = [(o, normalize(o.title)) for o in options]
    exact = [o for o, title in titles if title == text]
    if len(exact) == 1:
        return exact[0]

    def significant(value: str) -> str:
        return " ".join(w for w in value.split() if w not in _FILLER)

    core = significant(text)
    # A title's distinctive last word ("sharma" for "Dr. Anil Sharma"), unless another
    # offered title shares that word ("appointment" in two menu buttons).
    title_words = [set(significant(title).split()) for _, title in titles]
    spoken = set(core.split())
    contained = []
    for index, (option, title) in enumerate(titles):
        core_title = significant(title)
        if not core_title:
            continue
        last = core_title.split()[-1]
        shared = any(last in words for i, words in enumerate(title_words) if i != index)
        if f" {core_title} " in f" {core} " or (len(last) >= 3 and last in spoken and not shared):
            contained.append(option)
    if len(contained) == 1:
        return contained[0]
    return None
