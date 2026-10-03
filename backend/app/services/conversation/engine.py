"""The booking conversation: a deterministic state machine shared by every channel.

`handle()` takes a plain snapshot of the conversation and one normalized message, and returns
the new snapshot, the replies and the side effects to record. It never books anything itself:
bookings go through the inbound/booking services as a SystemActor, so channel rules (bots
create `pending_confirmation`, bots may only change their sender's own appointments) live in
one place. Persisting the snapshot, effects and replies is `turn.run_turn`'s job.

Global checks run before the current state, in this order: out-of-order messages, opt-out,
STOP, emergencies, handoff (bot paused), medical questions, "menu".
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AppointmentStatus, BotChannel, InboundChannel
from app.services import inbound
from app.services.booking import (
    BookingErrorCode,
    SystemActor,
    reschedule_appointment,
    update_appointment_status,
)
from app.services.booking.actor import SystemChannel
from app.services.booking.timeutil import local_date
from app.services.conversation import data
from app.services.conversation.dates import parse_time, resolve_date
from app.services.conversation.i18n import (
    LANGUAGE_TITLES,
    NOTICE,
    REASONS,
    day_label,
    english,
    first_name,
    t,
    time_label,
)
from app.services.conversation.intent import IntentRequest, Understander
from app.services.conversation.keywords import KeywordSet, is_medical_question, normalize
from app.services.conversation.options import match_option, options_from_draft, options_to_draft
from app.services.conversation.types import (
    LANGUAGES,
    MAX_BUTTONS,
    MAX_LIST_ROWS,
    ConvState,
    HandoffReason,
    InboundMsg,
    Language,
    OpenHandoff,
    Option,
    RaiseAlert,
    RecordConsent,
    Reply,
    SetOptOut,
    TurnOutcome,
)

MAX_FAILED_PARSES = 2
MORE = "more"

# States
NEW = "new"
LANGUAGE = "language"
MENU = "menu"
WHO = "who"
ASK_NAME = "ask_name"
DOCTOR = "doctor"
DATE = "date"
SLOT = "slot"
REASON = "reason"
CONFIRM = "confirm"
MY_APPTS = "my_appts"
APPT_ACTION = "appt_action"
CANCEL_CONFIRM = "cancel_confirm"
RESCHED_CONFIRM = "resched_confirm"
HANDOFF = "handoff"
OPTED_OUT = "opted_out"

_LANGUAGE_ALIASES: dict[str, Language] = {
    "telugu": "te",
    "తెలుగు": "te",
    "hindi": "hi",
    "हिंदी": "hi",
    "हिन्दी": "hi",
    "english": "en",
    "ఇంగ్లీష్": "en",
    "अंग्रेज़ी": "en",
    "इंग्लिश": "en",
}
_MENU_WORDS = frozenset(
    normalize(w)
    for w in ("menu", "hi", "hello", "hey", "start over", "మెనూ", "నమస్కారం", "मेनू", "नमस्ते")
)


@dataclass(frozen=True)
class TurnContext:
    clinic_id: UUID
    clinic_name: str
    tz: Any  # ZoneInfo
    now: datetime
    keywords: KeywordSet
    # The phone opted out (on any channel).
    opted_out: bool = False
    # Free-text / transcript understanding (rules or the LLM); None = menus only.
    understand: Understander | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def today(self) -> date:
        return local_date(self.now, self.tz)


@dataclass
class _Turn:
    """Mutable working state of one turn."""

    ctx: TurnContext
    session: AsyncSession
    msg: InboundMsg
    conv: ConvState
    replies: list[Reply] = field(default_factory=list)
    effects: list[Any] = field(default_factory=list)
    appointment_id: UUID | None = None

    @property
    def lang(self) -> Language | None:
        return self.conv.language

    @property
    def voice(self) -> bool:
        return self.conv.channel is not BotChannel.WHATSAPP

    def say(self, key: str, *, essential: bool = False, **values: object) -> None:
        self.replies.append(Reply(text=t(self.lang, key, **values), essential=essential))

    def outcome(self, **kwargs: Any) -> TurnOutcome:
        return TurnOutcome(
            state=self.conv,
            replies=self.replies,
            effects=self.effects,
            appointment_id=self.appointment_id,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Presenting choices
# ---------------------------------------------------------------------------


def _present(
    turn: _Turn,
    state: str,
    text: str,
    options: Sequence[Option],
    *,
    buttons: bool = False,
    offset: int = 0,
    **draft: Any,
) -> None:
    """Ask a question with options; remember them so typed/spoken answers can be matched."""
    limit = MAX_BUTTONS if (buttons or turn.voice) else MAX_LIST_ROWS
    page = list(options[offset : offset + limit])
    if offset + limit < len(options):
        page = [*options[offset : offset + limit - 1], Option(MORE, t(turn.lang, "row_more"))]
    if buttons and len(page) <= MAX_BUTTONS:
        reply = Reply(text=text, buttons=tuple(page))
    else:
        reply = Reply(text=text, rows=tuple(page), list_label=t(turn.lang, "list_choose"))
    turn.replies.append(reply)
    turn.conv = turn.conv.to(state).with_draft(
        options=options_to_draft(page),
        all_options=options_to_draft(options),
        offset=offset,
        prompt=text,
        buttons=buttons,
        **draft,
    )


def _more(turn: _Turn) -> None:
    """Show the next page of the options of the current question."""
    d = turn.conv.draft
    limit = MAX_BUTTONS if (d.get("buttons") or turn.voice) else MAX_LIST_ROWS
    options = [
        Option(id=str(o["id"]), title=str(o["title"]), description=o.get("description"))
        for o in d.get("all_options", [])
    ]
    _present(
        turn,
        turn.conv.state,
        str(d.get("prompt", "")),
        options,
        buttons=bool(d.get("buttons")),
        offset=int(d.get("offset", 0)) + limit - 1,
    )


def _show_menu(turn: _Turn, text: str | None = None) -> None:
    options = [
        Option("menu:book", t(turn.lang, "btn_book")),
        Option("menu:my", t(turn.lang, "btn_my")),
        Option("menu:reception", t(turn.lang, "btn_reception")),
    ]
    turn.conv = replace(turn.conv, draft={}, selected_patient_id=None)
    _present(turn, MENU, text or t(turn.lang, "menu"), options, buttons=True)


async def _fallback(turn: _Turn) -> None:
    """Unmatched input: try to understand free text / a transcript, else ask again."""
    if not await _understand(turn):
        _not_understood(turn)


async def _understand(turn: _Turn) -> bool:
    parser = turn.ctx.understand
    text = turn.msg.text.strip()
    if parser is None or turn.msg.kind not in ("text", "voice") or not text:
        return False
    doctors = await data.active_doctors(turn.session, turn.ctx.clinic_id)
    parsed = await parser.parse(
        IntentRequest(
            text=text, today=turn.ctx.today, doctors=[d.name for d in doctors], language=turn.lang
        )
    )
    if parsed.intent == "unknown":
        return False
    turn.conv = replace(turn.conv, failed_parse_count=0)
    if parsed.intent == "reception":
        _handoff(turn, "button")
    elif parsed.intent in ("my_appointments", "cancel", "reschedule"):
        await _show_my_appointments(turn)
    else:
        hints: dict[str, str] = {}
        doctor = next((d for d in doctors if d.name == parsed.doctor), None)
        if doctor is not None:
            hints["doctor_id"] = str(doctor.id)
        day = resolve_date(parsed.date_text, turn.ctx.today) if parsed.date_text else None
        if day is not None:
            hints["day"] = day.isoformat()
        at = parse_time(parsed.time_text) if parsed.time_text else None
        if at is not None:
            hints["time"] = at.strftime("%H:%M")
        await _start_booking(turn, hints, parsed.patient_name)
    return True


def _not_understood(turn: _Turn) -> None:
    failed = turn.conv.failed_parse_count + 1
    turn.conv = replace(turn.conv, failed_parse_count=failed)
    if failed >= MAX_FAILED_PARSES:
        _handoff(turn, "parse_failed")
        return
    d = turn.conv.draft
    options = options_from_draft(d)
    text = f"{t(turn.lang, 'not_understood')}\n{d.get('prompt', '')}".strip()
    if options:
        if d.get("buttons") and len(options) <= MAX_BUTTONS:
            turn.replies.append(Reply(text=text, buttons=tuple(options)))
        else:
            turn.replies.append(
                Reply(text=text, rows=tuple(options), list_label=t(turn.lang, "list_choose"))
            )
    else:
        _show_menu(turn, text)


def _handoff(turn: _Turn, reason: HandoffReason) -> None:
    turn.effects += [OpenHandoff(reason), RaiseAlert("handoff")]
    turn.say("handoff", essential=True)
    turn.conv = replace(turn.conv.to(HANDOFF), handoff_open=True, draft={})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def handle(
    session: AsyncSession, ctx: TurnContext, conv: ConvState, msg: InboundMsg
) -> TurnOutcome:
    turn = _Turn(ctx=ctx, session=session, msg=msg, conv=conv)
    text = msg.text if msg.kind in ("text", "voice") else ""
    stale = (
        msg.sent_at is not None
        and conv.last_message_ts is not None
        and msg.sent_at < conv.last_message_ts
    )
    if msg.sent_at is not None and not stale:
        turn.conv = replace(turn.conv, last_message_ts=msg.sent_at)

    if conv.state == OPTED_OUT or ctx.opted_out:
        if text and ctx.keywords.is_start(text):
            turn.effects += [SetOptOut(False), RecordConsent("opted_in")]
            turn.conv = turn.conv.to(MENU)
            _show_menu(turn)
            return turn.outcome()
        return turn.outcome(ignored=True)
    if text and ctx.keywords.is_stop(text):
        turn.effects += [SetOptOut(True), RecordConsent("opted_out")]
        turn.replies.append(Reply(text=t(turn.lang, "opted_out"), kind="opt_out", essential=True))
        turn.conv = replace(turn.conv.to(OPTED_OUT), draft={})
        return turn.outcome()
    if text and ctx.keywords.is_emergency(text):
        turn.effects += [RaiseAlert("emergency"), OpenHandoff("emergency")]
        turn.replies.append(Reply(text=t(turn.lang, "emergency"), kind="emergency", essential=True))
        turn.conv = replace(turn.conv.to(HANDOFF), handoff_open=True, draft={})
        return turn.outcome()
    if stale or conv.handoff_open:
        return turn.outcome(ignored=True)

    if conv.state == NEW:
        _start(turn)
        return turn.outcome()
    if msg.kind == "unsupported":
        turn.say("unsupported")
        return turn.outcome()
    if msg.kind == "voice" and not text:
        turn.say("voice_too_long" if msg.voice_error == "too_long" else "voice_failed")
        return turn.outcome()
    if text and is_medical_question(text):
        _show_menu(turn, f"{t(turn.lang, 'medical')}\n{t(turn.lang, 'menu')}")
        return turn.outcome()
    if text and normalize(text) in _MENU_WORDS and conv.state != LANGUAGE:
        _show_menu(turn)
        return turn.outcome()

    offered = options_from_draft(turn.conv.draft)
    choice = match_option(msg, offered) or _yes_no(text, offered)
    if choice is not None and choice.id == MORE:
        _more(turn)
        return turn.outcome()
    if choice is not None:
        turn.conv = replace(turn.conv, failed_parse_count=0)
    await _STATES.get(turn.conv.state, _on_menu)(turn, choice)
    return turn.outcome()


_YES = frozenset(
    normalize(w)
    for w in (
        "yes",
        "yeah",
        "ok",
        "okay",
        "sure",
        "confirm",
        "అవును",
        "సరే",
        "हाँ",
        "हां",
        "जी हाँ",
        "ठीक है",
    )
)
_NO = frozenset(normalize(w) for w in ("no", "nope", "వద్దు", "కాదు", "नहीं", "ना"))


def _yes_no(text: str, offered: Sequence[Option]) -> Option | None:
    """Typed or spoken yes/no for confirm questions (voice callers rarely say the title)."""
    cleaned = normalize(text)
    wanted = (
        ("c:yes", "x:yes") if cleaned in _YES else ("c:change", "x:no") if cleaned in _NO else ()
    )
    return next((o for o in offered if o.id in wanted), None)


def _start(turn: _Turn) -> None:
    """First contact: privacy notice and language choice (or the hinted language)."""
    turn.effects.append(RecordConsent("notice_shown"))
    hint = turn.msg.lang_hint
    if hint is not None:
        # The simulator (and later the phone line) picks the language up front.
        turn.conv = replace(turn.conv, language=hint)
        turn.effects.append(RecordConsent("consented"))
        _show_menu(
            turn, f"{t(hint, 'notice_short', clinic=turn.ctx.clinic_name)}\n{t(hint, 'menu')}"
        )
        return
    options = [Option(f"lang:{code}", LANGUAGE_TITLES[code]) for code in LANGUAGES]
    turn.replies.append(
        Reply(
            text=NOTICE.format(clinic=turn.ctx.clinic_name),
            buttons=tuple(options),
            kind="notice",
        )
    )
    turn.conv = turn.conv.to(LANGUAGE).with_draft(
        options=options_to_draft(options), prompt="", buttons=True
    )


# ---------------------------------------------------------------------------
# State handlers
# ---------------------------------------------------------------------------


async def _on_language(turn: _Turn, choice: Option | None) -> None:
    code: Language | None = None
    if choice is not None and choice.id.startswith("lang:"):
        value = choice.id.removeprefix("lang:")
        code = next((c for c in LANGUAGES if c == value), None)
    elif turn.msg.text:
        code = _LANGUAGE_ALIASES.get(normalize(turn.msg.text))
    if code is None:
        options = options_from_draft(turn.conv.draft)
        turn.replies.append(
            Reply(
                text="Choose a language / భాష ఎంచుకోండి / भाषा चुनें",
                buttons=tuple(options),
                kind="notice",
            )
        )
        return
    turn.conv = replace(turn.conv, language=code, failed_parse_count=0)
    turn.effects.append(RecordConsent("consented"))
    _show_menu(turn)


async def _on_menu(turn: _Turn, choice: Option | None) -> None:
    if choice is None:
        if turn.conv.state == MENU and turn.conv.draft.get("options"):
            await _fallback(turn)
        else:
            _show_menu(turn)
        return
    if choice.id == "menu:book":
        await _start_booking(turn)
    elif choice.id == "menu:my":
        await _show_my_appointments(turn)
    elif choice.id == "menu:reception":
        _handoff(turn, "button")
    else:
        _show_menu(turn)


async def _start_booking(
    turn: _Turn, hints: dict[str, str] | None = None, patient_name: str | None = None
) -> None:
    """Who is it for? Parsed free text may carry hints (doctor/day/time) for later steps."""
    people = await data.family(turn.session, turn.ctx.clinic_id, turn.conv.phone_e164)
    turn.conv = replace(
        turn.conv, draft={"mode": "book", "hints": hints or {}}, selected_patient_id=None
    )
    if patient_name:
        named = [
            p
            for p in people
            if first_name(p.name).casefold() == first_name(patient_name).casefold()
        ]
        if len(named) == 1:
            turn.conv = replace(turn.conv, selected_patient_id=named[0].id).with_draft(
                patient_name=named[0].name
            )
            await _ask_doctor(turn)
            return
    if not people:
        _ask_name(turn)
        return
    options = [Option(f"p:{p.id}", first_name(p.name)) for p in people]
    options.append(Option("p:new", t(turn.lang, "row_someone_else")))
    _present(turn, WHO, t(turn.lang, "who"), options, mode="book")


def _ask_name(turn: _Turn) -> None:
    turn.say("ask_name")
    turn.conv = turn.conv.to(ASK_NAME).with_draft(options=[], prompt=t(turn.lang, "ask_name"))


async def _on_who(turn: _Turn, choice: Option | None) -> None:
    if choice is None:
        await _fallback(turn)
        return
    if choice.id == "p:new":
        _ask_name(turn)
        return
    patient_id = UUID(choice.id.removeprefix("p:"))
    name = await data.patient_name(turn.session, turn.ctx.clinic_id, patient_id)
    if name is None:
        await _start_booking(turn)
        return
    turn.conv = replace(turn.conv, selected_patient_id=patient_id).with_draft(patient_name=name)
    await _ask_doctor(turn)


def _valid_name(text: str) -> str | None:
    name = " ".join(text.split())
    letters = sum(ch.isalpha() for ch in name)
    if not 2 <= len(name) <= 80 or letters < 2 or any(ch.isdigit() for ch in name):
        return None
    return name


async def _on_ask_name(turn: _Turn, choice: Option | None) -> None:
    name = _valid_name(turn.msg.text) if turn.msg.kind in ("text", "voice") else None
    if name is None:
        failed = turn.conv.failed_parse_count + 1
        turn.conv = replace(turn.conv, failed_parse_count=failed)
        if failed >= MAX_FAILED_PARSES:
            _handoff(turn, "parse_failed")
        else:
            turn.say("bad_name")
        return
    turn.conv = replace(turn.conv, selected_patient_id=None, failed_parse_count=0).with_draft(
        patient_name=name
    )
    await _ask_doctor(turn)


def _take_hint(turn: _Turn, key: str) -> str | None:
    """A parsed suggestion for this step, used once (so "Change" goes back to the lists)."""
    hints: dict[str, str] = dict(turn.conv.draft.get("hints") or {})
    value = hints.pop(key, None)
    if value is not None:
        turn.conv = turn.conv.with_draft(hints=hints)
    return value


async def _ask_doctor(turn: _Turn) -> None:
    doctors = await data.active_doctors(turn.session, turn.ctx.clinic_id)
    if not doctors:
        _show_menu(turn, t(turn.lang, "no_doctors"))
        return
    hinted = _take_hint(turn, "doctor_id")
    doctor = next((d for d in doctors if str(d.id) == hinted), None)
    if doctor is not None:
        turn.conv = turn.conv.with_draft(doctor_id=str(doctor.id), doctor_name=doctor.name)
        await _ask_date(turn)
        return
    options = [Option(f"d:{d.id}", d.name, d.specialization) for d in doctors]
    _present(turn, DOCTOR, t(turn.lang, "doctor"), options)


async def _on_doctor(turn: _Turn, choice: Option | None) -> None:
    if choice is None:
        await _fallback(turn)
        return
    doctor = await data.doctor(turn.session, turn.ctx.clinic_id, UUID(choice.id.removeprefix("d:")))
    if doctor is None:
        await _ask_doctor(turn)
        return
    turn.conv = turn.conv.with_draft(doctor_id=str(doctor.id), doctor_name=doctor.name)
    await _ask_date(turn)


async def _ask_date(turn: _Turn) -> None:
    d = turn.conv.draft
    doctor_id = UUID(d["doctor_id"])
    days = await data.open_days(
        turn.session, turn.ctx.clinic_id, doctor_id, turn.ctx.today, turn.ctx.now
    )
    if not days:
        text = t(turn.lang, "no_dates", doctor=d["doctor_name"])
        if d.get("mode") == "reschedule":
            _show_menu(turn, text)
            return
        turn.replies.append(Reply(text=text))
        await _ask_doctor(turn)
        return
    hinted = _take_hint(turn, "day")
    if hinted is not None and any(day.isoformat() == hinted for day, _ in days):
        turn.conv = turn.conv.with_draft(day=hinted)
        await _ask_slot(turn, date.fromisoformat(hinted))
        return
    options = [
        Option(
            f"day:{day.isoformat()}",
            day_label(turn.lang, day, turn.ctx.today),
            t(turn.lang, "slots_count", n=count),
        )
        for day, count in days
    ]
    _present(turn, DATE, t(turn.lang, "date", doctor=d["doctor_name"]), options)


async def _on_date(turn: _Turn, choice: Option | None) -> None:
    if choice is None and turn.msg.text:
        wanted = resolve_date(turn.msg.text, turn.ctx.today)
        if wanted is not None:
            choice = next(
                (o for o in _all_options(turn) if o.id == f"day:{wanted.isoformat()}"), None
            )
    if choice is None:
        await _fallback(turn)
        return
    day = date.fromisoformat(choice.id.removeprefix("day:"))
    turn.conv = replace(turn.conv, failed_parse_count=0).with_draft(day=day.isoformat())
    await _ask_slot(turn, day)


async def _ask_slot(turn: _Turn, day: date) -> None:
    d = turn.conv.draft
    slots = await data.free_slots(
        turn.session, turn.ctx.clinic_id, UUID(d["doctor_id"]), day, turn.ctx.now
    )
    if not slots:
        await _ask_date(turn)
        return
    options = [Option(f"t:{s.isoformat()}", time_label(s, turn.ctx.tz)) for s in slots]
    hinted = _take_hint(turn, "time")
    if hinted is not None:
        # The asked-for time first (if free), then the rest; the patient still picks.
        wanted = [o for o in options if _slot_time(o, turn) == hinted]
        options = wanted + [o for o in options if o not in wanted]
    label = day_label(turn.lang, day, turn.ctx.today)
    _present(turn, SLOT, t(turn.lang, "slot", day=label), options)


def _slot_time(option: Option, turn: _Turn) -> str:
    starts_at = datetime.fromisoformat(option.id.removeprefix("t:"))
    return starts_at.astimezone(turn.ctx.tz).strftime("%H:%M")


def _all_options(turn: _Turn) -> list[Option]:
    return [
        Option(id=str(o["id"]), title=str(o["title"]), description=o.get("description"))
        for o in turn.conv.draft.get("all_options", turn.conv.draft.get("options", []))
    ]


async def _on_slot(turn: _Turn, choice: Option | None) -> None:
    if choice is None and turn.msg.text:
        wanted = parse_time(turn.msg.text)
        if wanted is not None:
            choice = next(
                (
                    o
                    for o in _all_options(turn)
                    if datetime.fromisoformat(o.id.removeprefix("t:"))
                    .astimezone(turn.ctx.tz)
                    .time()
                    == wanted
                ),
                None,
            )
    if choice is None:
        await _fallback(turn)
        return
    starts_at = datetime.fromisoformat(choice.id.removeprefix("t:"))
    turn.conv = replace(turn.conv, failed_parse_count=0).with_draft(starts_at=starts_at.isoformat())
    if turn.conv.draft.get("mode") == "reschedule":
        _ask_resched_confirm(turn)
    else:
        _ask_reason(turn)


def _ask_reason(turn: _Turn) -> None:
    options = [Option(f"r:{code}", t(turn.lang, f"reason_{code}")) for code in REASONS]
    options.append(Option("r:skip", t(turn.lang, "reason_skip")))
    _present(turn, REASON, t(turn.lang, "reason"), options)


async def _on_reason(turn: _Turn, choice: Option | None) -> None:
    # Free text is not stored (no symptoms over chat); anything typed counts as "Other".
    code = choice.id.removeprefix("r:") if choice is not None else "other"
    reason = None if code == "skip" else english(f"reason_{code}")
    turn.conv = turn.conv.with_draft(reason=reason)
    _ask_confirm(turn)


def _summary_values(turn: _Turn) -> dict[str, str]:
    d = turn.conv.draft
    starts_at = datetime.fromisoformat(d["starts_at"])
    return {
        "patient": str(d.get("patient_name", "")),
        "doctor": str(d.get("doctor_name", "")),
        "day": day_label(turn.lang, local_date(starts_at, turn.ctx.tz), turn.ctx.today),
        "time": time_label(starts_at, turn.ctx.tz),
    }


def _confirm_buttons(turn: _Turn) -> list[Option]:
    return [
        Option("c:yes", t(turn.lang, "btn_confirm")),
        Option("c:change", t(turn.lang, "btn_change")),
    ]


def _ask_confirm(turn: _Turn) -> None:
    text = t(turn.lang, "confirm", **_summary_values(turn))
    _present(turn, CONFIRM, text, _confirm_buttons(turn), buttons=True)


async def _on_confirm(turn: _Turn, choice: Option | None) -> None:
    if choice is None:
        await _fallback(turn)
        return
    if choice.id == "c:change":
        await _ask_doctor(turn)
        return
    await _book(turn)


async def _book(turn: _Turn) -> None:
    """Submit the request through the inbound service (idempotent per attempt)."""
    conv, ctx = turn.conv, turn.ctx
    d = conv.draft
    channel = (
        InboundChannel.WHATSAPP if conv.channel is BotChannel.WHATSAPP else InboundChannel.VOICE
    )
    external_ref = f"{conv.id}:{conv.attempt_counter}"
    request = inbound.InboundBooking(
        channel=channel,
        external_ref=external_ref,
        caller_phone=conv.phone_e164,
        patient_name=str(d["patient_name"]),
        doctor_id=UUID(d["doctor_id"]),
        requested_time=datetime.fromisoformat(d["starts_at"]),
        reason=d.get("reason"),
    )
    raw = {
        "source": "bot",
        "conversation_id": str(conv.id),
        "doctor_id": d["doctor_id"],
        "requested_time": d["starts_at"],
        "reason": d.get("reason"),
    }
    stored, duplicate = await inbound.record_request(
        turn.session, ctx.clinic_id, channel, external_ref, raw
    )
    request_id = stored.id
    if duplicate:
        outcome = await inbound.describe(turn.session, stored)
    else:
        outcome = await inbound.process_request(turn.session, ctx.clinic_id, request_id, request)
    turn.conv = replace(turn.conv, attempt_counter=conv.attempt_counter + 1)

    if outcome.appointment is not None:
        turn.appointment_id = outcome.appointment.id
        turn.conv = replace(turn.conv.to(MENU), draft={}, selected_patient_id=None)
        turn.say("requested", essential=True)
        return
    if outcome.suggested and outcome.code is not BookingErrorCode.VALIDATION:
        # The bot recovers on its own, so this request needn't wait in reception's list.
        await inbound.mark_rejected(
            turn.session, ctx.clinic_id, request_id, "Handled by the bot: offered other times."
        )
        options = [
            Option(
                f"t:{s.starts_at.isoformat()}",
                time_label(s.starts_at, ctx.tz),
                day_label(turn.lang, local_date(s.starts_at, ctx.tz), ctx.today),
            )
            for s in outcome.suggested
        ]
        _present(turn, SLOT, t(turn.lang, "slot_taken"), options)
        return
    turn.say("booking_failed", essential=True)
    turn.effects += [OpenHandoff("parse_failed"), RaiseAlert("handoff")]
    turn.conv = replace(turn.conv.to(HANDOFF), handoff_open=True, draft={})


# --- My appointments, cancel and reschedule ---


def _actor(turn: _Turn) -> SystemActor:
    channel: SystemChannel = "whatsapp" if turn.conv.channel is BotChannel.WHATSAPP else "voice"
    return SystemActor(
        channel=channel, clinic_id=turn.ctx.clinic_id, phone_e164=turn.conv.phone_e164
    )


async def _show_my_appointments(turn: _Turn) -> None:
    items = await data.upcoming(
        turn.session, turn.ctx.clinic_id, turn.conv.phone_e164, turn.ctx.now
    )
    if not items:
        _show_menu(turn, f"{t(turn.lang, 'my_none')}\n{t(turn.lang, 'menu')}")
        return
    options = []
    for item in items:
        day = local_date(item.starts_at, turn.ctx.tz)
        status = (
            "status_pending"
            if item.status is AppointmentStatus.PENDING_CONFIRMATION
            else "status_scheduled"
        )
        options.append(
            Option(
                f"a:{item.id}",
                f"{first_name(item.patient_name)}, {day_label(turn.lang, day, turn.ctx.today)}",
                f"{time_label(item.starts_at, turn.ctx.tz)} · {item.doctor_name} · "
                f"{t(turn.lang, status)}",
            )
        )
    _present(turn, MY_APPTS, t(turn.lang, "my_list"), options, mode="manage")


async def _on_my_appts(turn: _Turn, choice: Option | None) -> None:
    if choice is None:
        await _fallback(turn)
        return
    appointment_id = UUID(choice.id.removeprefix("a:"))
    items = await data.upcoming(
        turn.session, turn.ctx.clinic_id, turn.conv.phone_e164, turn.ctx.now
    )
    item = next((i for i in items if i.id == appointment_id), None)
    if item is None:
        await _show_my_appointments(turn)
        return
    day = day_label(turn.lang, local_date(item.starts_at, turn.ctx.tz), turn.ctx.today)
    summary = (
        f"{item.patient_name}, {item.doctor_name}, {day} {time_label(item.starts_at, turn.ctx.tz)}"
    )
    options = [
        Option("act:cancel", t(turn.lang, "btn_cancel_appt")),
        Option("act:resched", t(turn.lang, "btn_reschedule")),
        Option("act:back", t(turn.lang, "btn_back")),
    ]
    _present(
        turn,
        APPT_ACTION,
        t(turn.lang, "appt_action", summary=summary),
        options,
        buttons=True,
        mode="manage",
        appointment_id=str(item.id),
        doctor_id=str(item.doctor_id),
        doctor_name=item.doctor_name,
        patient_name=item.patient_name,
    )


async def _on_appt_action(turn: _Turn, choice: Option | None) -> None:
    if choice is None:
        await _fallback(turn)
        return
    if choice.id == "act:cancel":
        options = [
            Option("x:yes", t(turn.lang, "btn_yes_cancel")),
            Option("x:no", t(turn.lang, "btn_no")),
        ]
        _present(turn, CANCEL_CONFIRM, t(turn.lang, "cancel_confirm"), options, buttons=True)
    elif choice.id == "act:resched":
        turn.conv = turn.conv.with_draft(mode="reschedule")
        await _ask_date(turn)
    else:
        await _show_my_appointments(turn)


async def _on_cancel_confirm(turn: _Turn, choice: Option | None) -> None:
    if choice is None:
        await _fallback(turn)
        return
    if choice.id != "x:yes":
        _show_menu(turn)
        return
    appointment_id = UUID(turn.conv.draft["appointment_id"])
    result = await update_appointment_status(
        turn.session, appointment_id, AppointmentStatus.CANCELLED, _actor(turn)
    )
    if result.ok:
        turn.appointment_id = appointment_id
        _show_menu(turn, f"{t(turn.lang, 'cancelled')}\n{t(turn.lang, 'menu')}")
    else:
        _show_menu(turn, f"{t(turn.lang, 'change_failed')}\n{t(turn.lang, 'menu')}")


def _ask_resched_confirm(turn: _Turn) -> None:
    text = t(turn.lang, "resched_confirm", **_summary_values(turn))
    _present(turn, RESCHED_CONFIRM, text, _confirm_buttons(turn), buttons=True)


async def _on_resched_confirm(turn: _Turn, choice: Option | None) -> None:
    if choice is None:
        await _fallback(turn)
        return
    if choice.id == "c:change":
        await _ask_date(turn)
        return
    d = turn.conv.draft
    appointment_id = UUID(d["appointment_id"])
    starts_at = datetime.fromisoformat(d["starts_at"])
    result = await reschedule_appointment(
        turn.session, appointment_id, starts_at, _actor(turn), now=turn.ctx.now
    )
    if result.ok:
        turn.appointment_id = appointment_id
        turn.conv = replace(turn.conv.to(MENU), draft={})
        turn.say("rescheduled")
    elif result.code is BookingErrorCode.SLOT_TAKEN:
        turn.say("slot_taken")
        await _ask_slot(turn, local_date(starts_at, turn.ctx.tz))
    else:
        _show_menu(turn, f"{t(turn.lang, 'change_failed')}\n{t(turn.lang, 'menu')}")


async def _on_handoff(turn: _Turn, choice: Option | None) -> None:
    # Reached only after reception resumed the bot (handoff closed) without a new state.
    _show_menu(turn)


_STATES = {
    LANGUAGE: _on_language,
    MENU: _on_menu,
    WHO: _on_who,
    ASK_NAME: _on_ask_name,
    DOCTOR: _on_doctor,
    DATE: _on_date,
    SLOT: _on_slot,
    REASON: _on_reason,
    CONFIRM: _on_confirm,
    MY_APPTS: _on_my_appts,
    APPT_ACTION: _on_appt_action,
    CANCEL_CONFIRM: _on_cancel_confirm,
    RESCHED_CONFIRM: _on_resched_confirm,
    HANDOFF: _on_handoff,
}
