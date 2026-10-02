from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, BeforeValidator, StringConstraints


def _blank_to_none(value: Any) -> Any:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _text(max_length: int) -> Any:
    return Annotated[
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)
        ]
        | None,
        BeforeValidator(_blank_to_none),
    ]


# Optional free text: trimmed, blank becomes null.
ShortText = _text(200)
NoteText = _text(1000)
# Clinical record fields.
ItemText = _text(50)
ShortClinicalText = _text(5000)
ClinicalText = _text(10000)

# Response timestamps are always UTC ("...Z"); clients convert to clinic time for display.
UtcDateTime = Annotated[datetime, AfterValidator(lambda value: value.astimezone(UTC))]

# Required single-line name.
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
