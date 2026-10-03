"""Turn the engine's replies into one short spoken prompt (voice simulator, later the phone).

The engine already limits spoken menus to three options (with "more" paging) and its confirm
summaries read back patient, doctor, day and time. Here line breaks become pauses and the
options are read as numbers the caller can say ("say 2 for ...").
"""

from app.services.conversation.types import Language, Reply

_OPTION = {
    "te": "{title} కోసం {n} అనండి.",
    "hi": "{title} के लिए {n} बोलें।",
    "en": "Say {n} for {title}.",
}
_END = {"te": ".", "hi": "।", "en": "."}


def _sentence(line: str, language: Language) -> str:
    line = line.strip().lstrip("•").strip()
    if not line:
        return ""
    return line if line[-1] in ".?!।:" else f"{line}{_END[language]}"


def speakable(replies: list[Reply], language: Language) -> str:
    parts: list[str] = []
    for reply in replies:
        parts += [s for line in reply.text.splitlines() if (s := _sentence(line, language))]
        for n, option in enumerate((*reply.buttons, *reply.rows), start=1):
            title = (
                option.title if not option.description else f"{option.title}, {option.description}"
            )
            parts.append(_OPTION[language].format(n=n, title=title))
    return " ".join(parts)
