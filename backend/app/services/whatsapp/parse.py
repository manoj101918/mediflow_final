"""Parse Meta WhatsApp Cloud API webhook payloads (messages and delivery statuses).

Payload shape: entry[].changes[].value with `metadata.phone_number_id`, `messages[]` and
`statuses[]`. Only changes for our phone number id are used. Senders arrive without "+".
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services.booking import normalize_phone


@dataclass(frozen=True)
class IncomingMessage:
    wamid: str
    phone_e164: str
    type: str  # text | interactive | button | audio | location | image | ...
    sent_at: datetime
    text: str = ""
    reply_id: str | None = None
    media_id: str | None = None
    mime_type: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        """The engine's message kind."""
        if self.reply_id is not None:
            return "reply"
        if self.type == "text":
            return "text"
        if self.type == "audio":
            return "voice"
        if self.type == "location":
            return "location"
        return "unsupported"


@dataclass(frozen=True)
class StatusUpdate:
    wamid: str
    status: str  # sent | delivered | read | failed
    at: datetime
    error: str | None = None


@dataclass(frozen=True)
class WebhookBatch:
    messages: list[IncomingMessage]
    statuses: list[StatusUpdate]


def _timestamp(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


def message_from_raw(raw: dict[str, Any]) -> IncomingMessage | None:
    wamid = raw.get("id")
    phone = normalize_phone(f"+{raw.get('from', '')}")
    if not isinstance(wamid, str) or not wamid or phone is None:
        return None
    kind = str(raw.get("type", "unknown"))
    text, reply_id, media_id, mime = "", None, None, None
    if kind == "text":
        text = str(raw.get("text", {}).get("body", ""))
    elif kind == "interactive":
        interactive = raw.get("interactive", {})
        chosen = interactive.get("button_reply") or interactive.get("list_reply") or {}
        reply_id = chosen.get("id")
        text = str(chosen.get("title", ""))
    elif kind == "button":  # quick-reply button of a template message
        reply_id = raw.get("button", {}).get("payload")
        text = str(raw.get("button", {}).get("text", ""))
    elif kind == "audio":
        audio = raw.get("audio", {})
        media_id = audio.get("id")
        mime = audio.get("mime_type")
    return IncomingMessage(
        wamid=wamid,
        phone_e164=phone,
        type=kind,
        sent_at=_timestamp(raw.get("timestamp")),
        text=text[:4096],
        reply_id=str(reply_id) if reply_id else None,
        media_id=media_id,
        mime_type=mime,
        raw=raw,
    )


def _status(raw: dict[str, Any]) -> StatusUpdate | None:
    wamid, status = raw.get("id"), raw.get("status")
    if not isinstance(wamid, str) or status not in ("sent", "delivered", "read", "failed"):
        return None
    errors = raw.get("errors") or []
    error = None
    if errors and isinstance(errors[0], dict):
        first = errors[0]
        error = f"{first.get('code', '')}: {first.get('title', '')}"[:500]
    return StatusUpdate(
        wamid=wamid, status=status, at=_timestamp(raw.get("timestamp")), error=error
    )


def parse_webhook(payload: dict[str, Any], phone_number_id: str | None) -> WebhookBatch:
    messages: list[IncomingMessage] = []
    statuses: list[StatusUpdate] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            if phone_number_id and metadata.get("phone_number_id") != phone_number_id:
                continue
            messages += [m for raw in value.get("messages") or [] if (m := message_from_raw(raw))]
            statuses += [s for raw in value.get("statuses") or [] if (s := _status(raw))]
    return WebhookBatch(messages=messages, statuses=statuses)
