"""Normalized messages in and out of the conversation engine (channel-agnostic)."""

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.db.models import BotChannel

Language = Literal["te", "hi", "en"]
LANGUAGES: tuple[Language, ...] = ("te", "hi", "en")
InboundKind = Literal["text", "reply", "voice", "location", "unsupported"]
ReplyKind = Literal["reply", "notice", "emergency", "opt_out"]
HandoffReason = Literal["button", "parse_failed", "emergency"]
VoiceError = Literal["too_long", "failed"]

# WhatsApp interactive limits (also used to keep voice prompts short).
MAX_BUTTONS = 3
MAX_LIST_ROWS = 10
BUTTON_TITLE_MAX = 20
ROW_TITLE_MAX = 24
ROW_DESCRIPTION_MAX = 72


@dataclass(frozen=True)
class InboundMsg:
    """One message from a patient, whatever the channel."""

    channel: BotChannel
    phone_e164: str
    kind: InboundKind
    # Typed text, the transcript of a voice note, or the title of the chosen button/row.
    text: str = ""
    # Id of the chosen button or list row (interactive replies only).
    reply_id: str | None = None
    lang_hint: Language | None = None
    # channel_messages.id of the stored message (idempotency of replies).
    message_id: UUID | None = None
    # wamid or simulator id: evidence for consent events.
    external_id: str | None = None
    # When the patient sent it (Meta's timestamp); used to spot out-of-order delivery.
    sent_at: datetime | None = None
    # Voice notes that could not be transcribed.
    voice_error: VoiceError | None = None


@dataclass(frozen=True)
class Option:
    id: str
    title: str
    description: str | None = None


@dataclass(frozen=True)
class Reply:
    """A message to send: plain text, text + up to 3 buttons, or text + a list (≤10 rows)."""

    text: str
    buttons: tuple[Option, ...] = ()
    rows: tuple[Option, ...] = ()
    list_label: str | None = None
    kind: ReplyKind = "reply"
    # Essential replies may use the reserved part of the free monthly allowance.
    essential: bool = False

    def as_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"text": self.text}
        if self.buttons:
            body["buttons"] = [_option_dict(o) for o in self.buttons]
        if self.rows:
            body["rows"] = [_option_dict(o) for o in self.rows]
            body["list_label"] = self.list_label
        return body


def _option_dict(option: Option) -> dict[str, Any]:
    data: dict[str, Any] = {"id": option.id, "title": option.title}
    if option.description:
        data["description"] = option.description
    return data


@dataclass(frozen=True)
class ConvState:
    """Plain snapshot of a bot_conversations row.

    The engine never holds ORM objects across booking-service calls (they commit or roll back
    and would expire them); it works on this snapshot and saves it with a version check.
    """

    id: UUID
    clinic_id: UUID
    channel: BotChannel
    phone_e164: str
    state: str
    language: Language | None
    selected_patient_id: UUID | None
    draft: dict[str, Any]
    attempt_counter: int
    failed_parse_count: int
    handoff_open: bool
    last_message_ts: datetime | None
    version: int

    def to(self, state: str, **changes: Any) -> "ConvState":
        return replace(self, state=state, **changes)

    def with_draft(self, **values: Any) -> "ConvState":
        return replace(self, draft={**self.draft, **values})


# --- Side effects the engine asks for; applied in the same transaction as the state. ---


@dataclass(frozen=True)
class OpenHandoff:
    reason: "HandoffReason"


@dataclass(frozen=True)
class RaiseAlert:
    kind: Literal["emergency", "handoff"]


@dataclass(frozen=True)
class RecordConsent:
    action: Literal["notice_shown", "consented", "opted_out", "opted_in"]


@dataclass(frozen=True)
class SetOptOut:
    opted_out: bool


Effect = OpenHandoff | RaiseAlert | RecordConsent | SetOptOut


@dataclass
class TurnOutcome:
    state: ConvState
    replies: list[Reply] = field(default_factory=list)
    effects: list[Effect] = field(default_factory=list)
    # The message was recorded but not acted on (stale or bot paused).
    ignored: bool = False
    # Appointment created or changed in this turn (for the transcript / simulator).
    appointment_id: UUID | None = None
