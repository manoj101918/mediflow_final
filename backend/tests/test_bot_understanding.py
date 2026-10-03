"""Free text and voice notes: closed intents, suggestions only, buttons always confirm."""

from collections.abc import AsyncIterator
from datetime import date, datetime, time
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlalchemy import select

from app.db.models import Appointment, AppointmentStatus, ChannelMessage, MessageDirection
from app.services.conversation.i18n import t
from app.services.conversation.intent import (
    GroqParser,
    IntentRequest,
    RuleParser,
    match_doctor,
)
from tests.api_utils import IST, TOMORROW
from tests.bot_utils import Bot
from tests.conftest import ClinicFixture
from tests.whatsapp_utils import WhatsAppHarness, add_bot_doctor

DOCTORS = ["Dr. Anil Sharma", "Dr. Lakshmi Iyer", "Dr. Imran Khan"]
THURSDAY = date(2026, 10, 1)
TELUGU = "రేపు డాక్టర్ శర్మ దగ్గర అపాయింట్‌మెంట్ కావాలి"


def _request(text: str) -> IntentRequest:
    return IntentRequest(text=text, today=THURSDAY, doctors=DOCTORS, language=None)


@pytest.mark.parametrize(
    ("spoken", "doctor"),
    [
        ("శర్మ", "Dr. Anil Sharma"),
        ("शर्मा", "Dr. Anil Sharma"),
        ("sharma", "Dr. Anil Sharma"),
        ("इमरान", "Dr. Imran Khan"),
        ("ఖాన్", "Dr. Imran Khan"),
        ("lakshmi", "Dr. Lakshmi Iyer"),
        ("fever", None),
    ],
)
def test_doctor_names_match_across_scripts(spoken: str, doctor: str | None) -> None:
    assert match_doctor(f"doctor {spoken} please", DOCTORS) == doctor


@pytest.mark.parametrize(
    ("text", "intent", "doctor", "has_date", "has_time"),
    [
        (TELUGU, "book", "Dr. Anil Sharma", True, False),
        ("कल शाम 5 बजे डॉक्टर शर्मा से मिलना है", "book", "Dr. Anil Sharma", True, True),
        ("Book Dr Khan on Tuesday at 10:30", "book", "Dr. Imran Khan", True, True),
        ("I want to cancel my appointment", "cancel", None, False, False),
        ("నా అపాయింట్‌మెంట్ ఎప్పుడు?", "my_appointments", None, False, False),
        ("please let me talk to reception", "reception", None, False, False),
        ("what's the weather like", "unknown", None, False, False),
    ],
)
async def test_rule_parser(
    text: str, intent: str, doctor: str | None, has_date: bool, has_time: bool
) -> None:
    parsed = await RuleParser().parse(_request(text))
    assert parsed.intent == intent
    assert parsed.doctor == doctor
    assert (parsed.date_text is not None) is has_date
    assert (parsed.time_text is not None) is has_time


async def test_llm_output_is_validated_and_falls_back_to_rules() -> None:
    reply = (
        '{"intent": "book", "doctor": "Sharma", "date_text": "రేపు", '
        '"time_text": null, "patient_name": null, "diagnosis": "flu"}'
    )
    parsed = await GroqParser(FakeListChatModel(responses=[reply])).parse(_request(TELUGU))
    # "Sharma" isn't a listed name: the transliterating matcher picks the real one.
    assert (parsed.intent, parsed.doctor, parsed.date_text) == ("book", "Dr. Anil Sharma", "రేపు")

    nonsense = GroqParser(FakeListChatModel(responses=["I think you should rest."]))
    assert (await nonsense.parse(_request(TELUGU))).intent == "book"  # rules took over

    invented = GroqParser(FakeListChatModel(responses=['{"intent": "prescribe"}']))
    assert (await invented.parse(_request("hmm"))).intent == "unknown"


async def test_telugu_free_text_suggests_but_never_books_without_confirm(
    clinic: ClinicFixture,
) -> None:
    await add_bot_doctor(clinic)
    await add_bot_doctor(clinic, "Dr. Lakshmi Iyer")
    bot = Bot(clinic, "+919811100001", understand=RuleParser())
    await bot.start("te")
    await bot.send(TELUGU)
    assert bot.texts() == [t("te", "ask_name")]
    await bot.send("Ravi Kumar")

    # Doctor and day were taken from the message: straight to tomorrow's slots.
    conversation = await bot.conversation()
    assert conversation.state == "slot"
    assert conversation.draft["doctor_name"] == "Dr. Anil Sharma"
    assert conversation.draft["day"] == TOMORROW.isoformat()
    assert all(option_id.startswith("t:") for option_id, _ in bot.options())

    await bot.send("అవును")  # "yes" is not a slot choice
    async with clinic.sessionmaker() as session:
        assert (
            await session.scalar(select(Appointment.id).where(Appointment.clinic_id == clinic.id))
            is None
        )

    await bot.press("t:")
    await bot.press("r:general")
    await bot.send("అవును")  # spoken "yes" at the confirm step
    async with clinic.sessionmaker() as session:
        appointment = await session.scalar(
            select(Appointment).where(Appointment.clinic_id == clinic.id)
        )
    assert appointment is not None and appointment.status is AppointmentStatus.PENDING_CONFIRMATION


async def test_asked_time_is_offered_first(clinic: ClinicFixture) -> None:
    await add_bot_doctor(clinic)
    bot = Bot(clinic, "+919811100001", understand=RuleParser())
    await bot.start()
    await bot.send("Book Dr Sharma tomorrow at 10:30")
    await bot.send("Ravi Kumar")
    first_id, _ = bot.options()[0]
    assert datetime.fromisoformat(first_id.removeprefix("t:")) == datetime.combine(
        TOMORROW, time(10, 30), tzinfo=IST
    )
    assert (await bot.conversation()).state == "slot"


async def test_free_text_routes_to_reception_and_my_appointments(clinic: ClinicFixture) -> None:
    bot = Bot(clinic, "+919811100001", understand=RuleParser())
    await bot.start("hi")
    await bot.send("मेरे अपॉइंटमेंट दिखाओ")
    assert bot.texts()[0].startswith(t("hi", "my_none"))
    await bot.send("रिसेप्शन से बात करनी है")
    assert bot.texts() == [t("hi", "handoff")]


async def test_two_unparseable_messages_hand_off(clinic: ClinicFixture) -> None:
    bot = Bot(
        clinic,
        "+919811100001",
        understand=GroqParser(FakeListChatModel(responses=["???", "!!!"])),
    )
    await bot.start()
    await bot.send("asdf qwer")
    await bot.send("zxcv tyui")
    conversation = await bot.conversation()
    assert conversation.handoff_reason == "parse_failed"


@pytest.fixture
async def voice(wa: WhatsAppHarness) -> AsyncIterator[WhatsAppHarness]:
    await add_bot_doctor(wa.clinic)
    await wa.say("hello")
    await wa.choose("lang:te")
    yield wa


async def _messages(wa: WhatsAppHarness, **where: Any) -> list[ChannelMessage]:
    async with wa.clinic.sessionmaker() as session:
        rows = await session.scalars(
            select(ChannelMessage)
            .where(ChannelMessage.clinic_id == wa.clinic.id, ChannelMessage.type == "audio")
            .filter_by(**where)
        )
        return list(rows)


async def test_voice_note_is_transcribed_and_only_the_transcript_kept(
    voice: WhatsAppHarness,
) -> None:
    voice.fake.media["MEDIA-1"] = (TELUGU.encode(), "audio/ogg; codecs=opus")
    await voice.voice("MEDIA-1")
    await voice.run()
    assert voice.last_body()["text"] == t("te", "ask_name")

    [message] = await _messages(voice, direction=MessageDirection.INBOUND)
    assert message.transcript == TELUGU
    # The stored payload is Meta's JSON (a media id), never the audio itself.
    assert message.payload["audio"] == {
        "id": "MEDIA-1",
        "mime_type": "audio/ogg; codecs=opus",
        "voice": True,
    }
    assert TELUGU.encode() not in str(message.payload).encode()

    await voice.say("Ravi Kumar")
    assert all(row["id"].startswith("t:") for row in voice.last_body()["rows"])


async def test_long_or_broken_voice_notes_get_a_helpful_reply(voice: WhatsAppHarness) -> None:
    voice.fake.media["LONG"] = (b"TOO_LONG", "audio/ogg")
    await voice.voice("LONG")
    await voice.run()
    assert voice.last_body()["text"] == t("te", "voice_too_long")

    await voice.voice("MISSING")  # Meta no longer has the media
    await voice.run()
    assert voice.last_body()["text"] == t("te", "voice_failed")
