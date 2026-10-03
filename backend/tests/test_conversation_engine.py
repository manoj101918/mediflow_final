"""The booking conversation end to end against the real booking service (fake-free: no AI)."""

from datetime import datetime, time, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.db.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
    BotAlert,
    BotChannel,
    ConsentEvent,
    ContactPreference,
    HandoffStatus,
    InboundBookingRequest,
    InboundStatus,
    Patient,
)
from app.services.booking import NewAppointment, create_appointment
from app.services.conversation.i18n import t
from app.services.conversation.types import Language
from tests.api_utils import EVERY_DAY, IST, TODAY, TOMORROW
from tests.bot_utils import Bot
from tests.conftest import ClinicFixture

S = AppointmentStatus
PHONE = "+919811100001"


async def _doctor(clinic: ClinicFixture, name: str = "Dr. Anil Sharma") -> UUID:
    return await clinic.add_doctor(name=name, windows=((time(9), time(11)),), weekdays=EVERY_DAY)


async def _appointments(clinic: ClinicFixture) -> list[Appointment]:
    async with clinic.sessionmaker() as session:
        rows = await session.scalars(
            select(Appointment)
            .where(Appointment.clinic_id == clinic.id)
            .order_by(Appointment.starts_at)
        )
        return list(rows)


async def _book_until_confirm(bot: Bot, *, who: str | None = None) -> None:
    """From the menu to the confirm summary (tomorrow, first free slot, fever)."""
    await bot.press("menu:book")
    if who is None:
        await bot.send("Ravi Kumar")
    else:
        await bot.press(who)
    await bot.press("d:")
    await bot.press(f"day:{TOMORROW.isoformat()}")
    await bot.press("t:")
    await bot.press("r:fever")


@pytest.mark.parametrize("language", ["te", "hi", "en"])
async def test_menu_booking_in_each_language(clinic: ClinicFixture, language: Language) -> None:
    await _doctor(clinic)
    bot = Bot(clinic, PHONE)

    first = await bot.send("hi")
    assert first.replies[0].kind == "notice"
    assert [o.id for o in first.replies[0].buttons] == ["lang:te", "lang:hi", "lang:en"]

    await bot.press(f"lang:{language}")
    assert bot.texts() == [t(language, "menu")]
    assert [o for o, _ in bot.options()] == ["menu:book", "menu:my", "menu:reception"]

    await _book_until_confirm(bot)
    assert bot.texts()[0].startswith(
        t(language, "confirm", patient="", doctor="", day="", time="")[:8]
    )
    assert await _appointments(clinic) == []  # nothing is booked before Confirm

    done = await bot.press("c:yes")
    assert bot.texts() == [t(language, "requested")]
    [appointment] = await _appointments(clinic)
    assert appointment.status is S.PENDING_CONFIRMATION
    assert appointment.source is AppointmentSource.WHATSAPP
    assert appointment.reason_for_visit == "Fever / cold"
    assert appointment.external_ref == f"{done.conversation_id}:0"
    assert done.appointment_id == appointment.id

    async with clinic.sessionmaker() as session:
        actions = list(
            await session.scalars(
                select(ConsentEvent.action)
                .where(ConsentEvent.clinic_id == clinic.id)
                .order_by(ConsentEvent.id)
            )
        )
        preference = await session.scalar(
            select(ContactPreference).where(ContactPreference.clinic_id == clinic.id)
        )
    assert actions == ["notice_shown", "consented"]
    assert preference is not None and preference.opted_in_at is not None


async def test_replies_are_queued_once_per_inbound_message(clinic: ClinicFixture) -> None:
    await _doctor(clinic)
    bot = Bot(clinic, PHONE)
    await bot.start()
    outbox = await bot.outbox()
    assert [row.kind for row in outbox] == ["notice", "reply"]
    assert len({row.idempotency_key for row in outbox}) == 2


async def test_family_members_sharing_a_phone(clinic: ClinicFixture) -> None:
    await _doctor(clinic)
    lakshmi = await clinic.add_patient("Lakshmi Devi", PHONE)
    ravi = await clinic.add_patient("Ravi Kumar", PHONE)
    bot = Bot(clinic, PHONE)
    await bot.start("te")

    await bot.press("menu:book")
    titles = [title for _, title in bot.options()]
    assert titles == ["Lakshmi", "Ravi", t("te", "row_someone_else")]

    await bot.send("Ravi")  # typed first name matches the row
    await bot.press("d:")
    await bot.press(f"day:{TOMORROW.isoformat()}")
    await bot.press("t:")
    await bot.press("r:skip")
    await bot.press("c:yes")

    [appointment] = await _appointments(clinic)
    assert appointment.patient_id == ravi
    assert appointment.patient_id != lakshmi
    assert appointment.reason_for_visit is None


async def test_someone_else_reuses_a_matching_patient(clinic: ClinicFixture) -> None:
    await _doctor(clinic)
    lakshmi = await clinic.add_patient("Lakshmi Devi", PHONE)
    bot = Bot(clinic, PHONE)
    await bot.start()
    await bot.press("menu:book")
    await bot.press("p:new")
    await bot.send("Lakshmi Devi")
    await bot.press("d:")
    await bot.press(f"day:{TOMORROW.isoformat()}")
    await bot.press("t:")
    await bot.press("r:other")
    await bot.press("c:yes")

    [appointment] = await _appointments(clinic)
    assert appointment.patient_id == lakshmi
    async with clinic.sessionmaker() as session:
        count = await session.scalar(
            select(func.count()).select_from(Patient).where(Patient.clinic_id == clinic.id)
        )
    assert count == 1


async def test_slot_taken_between_listing_and_confirm(clinic: ClinicFixture) -> None:
    doctor = await _doctor(clinic)
    bot = Bot(clinic, PHONE)
    await bot.start()
    await _book_until_confirm(bot)
    chosen = datetime.fromisoformat((await bot.conversation()).draft["starts_at"])

    other = await clinic.add_patient("Walk In", "+919800000077")
    async with clinic.sessionmaker() as session:
        taken = await create_appointment(
            session,
            NewAppointment(
                patient_id=other,
                doctor_id=doctor,
                starts_at=chosen,
                source=AppointmentSource.WALK_IN,
            ),
            await clinic.staff(),
        )
        assert taken.ok

    await bot.press("c:yes")
    assert bot.texts() == [t("en", "slot_taken")]
    suggestions = [option_id for option_id, _ in bot.options()]
    assert suggestions and all(option_id.startswith("t:") for option_id in suggestions)

    async with clinic.sessionmaker() as session:
        request = await session.scalar(
            select(InboundBookingRequest).where(InboundBookingRequest.clinic_id == clinic.id)
        )
    assert request is not None and request.status is InboundStatus.REJECTED

    await bot.press("t:")
    await bot.press("r:skip")
    done = await bot.press("c:yes")
    assert bot.texts() == [t("en", "requested")]
    mine = [a for a in await _appointments(clinic) if a.source is AppointmentSource.WHATSAPP]
    assert len(mine) == 1
    assert mine[0].external_ref == f"{done.conversation_id}:1"


async def test_typed_day_and_time_are_understood(clinic: ClinicFixture) -> None:
    await _doctor(clinic)
    bot = Bot(clinic, PHONE)
    await bot.start("hi")
    await bot.press("menu:book")
    await bot.send("Ravi Kumar")
    await bot.send("Sharma")
    assert bot.option_id("day:")
    await bot.send("कल")
    await bot.send("10:30")
    draft = (await bot.conversation()).draft
    assert datetime.fromisoformat(draft["starts_at"]).astimezone(IST) == datetime.combine(
        TOMORROW, time(10, 30), tzinfo=IST
    )


async def _scheduled_tomorrow(clinic: ClinicFixture) -> tuple[UUID, UUID]:
    doctor = await _doctor(clinic)
    patient = await clinic.add_patient("Ravi Kumar", PHONE)
    appointment = await clinic.add_appointment(
        doctor,
        patient,
        status="scheduled",
        starts_at=datetime.combine(TOMORROW, time(9), tzinfo=IST),
    )
    return doctor, appointment


async def test_cancel_from_my_appointments(clinic: ClinicFixture) -> None:
    _, appointment_id = await _scheduled_tomorrow(clinic)
    bot = Bot(clinic, PHONE)
    await bot.start()
    await bot.press("menu:my")
    await bot.press(f"a:{appointment_id}")
    await bot.press("act:cancel")
    await bot.press("x:yes")
    assert bot.texts()[0].startswith(t("en", "cancelled"))
    [appointment] = await _appointments(clinic)
    assert appointment.status is S.CANCELLED


async def test_reschedule_from_my_appointments(clinic: ClinicFixture) -> None:
    _, appointment_id = await _scheduled_tomorrow(clinic)
    bot = Bot(clinic, PHONE)
    await bot.start("te")
    await bot.press("menu:my")
    await bot.press(f"a:{appointment_id}")
    await bot.press("act:resched")
    await bot.press(f"day:{TOMORROW.isoformat()}")
    new_time = datetime.combine(TOMORROW, time(10), tzinfo=IST)
    await bot.press(f"t:{new_time.isoformat()}")
    await bot.press("c:yes")
    assert bot.texts() == [t("te", "rescheduled")]
    [appointment] = await _appointments(clinic)
    assert appointment.status is S.PENDING_CONFIRMATION
    assert appointment.starts_at == new_time


async def test_my_appointments_only_shows_this_phone(clinic: ClinicFixture) -> None:
    doctor, _ = await _scheduled_tomorrow(clinic)
    stranger = await clinic.add_patient("Someone Else", "+919800000055")
    await clinic.add_appointment(
        doctor,
        stranger,
        status="scheduled",
        starts_at=datetime.combine(TOMORROW, time(10), tzinfo=IST),
    )
    bot = Bot(clinic, PHONE)
    await bot.start()
    await bot.press("menu:my")
    assert len([o for o, _ in bot.options() if o.startswith("a:")]) == 1


async def test_handoff_pauses_the_bot(clinic: ClinicFixture) -> None:
    bot = Bot(clinic, PHONE)
    await bot.start()
    await bot.press("menu:reception")
    assert bot.texts() == [t("en", "handoff")]
    conversation = await bot.conversation()
    assert conversation.handoff_status is HandoffStatus.OPEN
    assert conversation.handoff_reason == "button"

    paused = await bot.send("hello?")
    assert paused.ignored and paused.replies == []
    async with clinic.sessionmaker() as session:
        kinds = list(
            await session.scalars(select(BotAlert.kind).where(BotAlert.clinic_id == clinic.id))
        )
    assert kinds == ["handoff"]


async def test_two_failed_parses_hand_off(clinic: ClinicFixture) -> None:
    bot = Bot(clinic, PHONE)
    await bot.start()
    await bot.send("qwerty asdf")
    assert bot.texts()[0].startswith(t("en", "not_understood"))
    await bot.send("zzz yyy")
    assert bot.texts() == [t("en", "handoff")]
    assert (await bot.conversation()).handoff_reason == "parse_failed"


async def test_stop_opts_out_on_every_channel(clinic: ClinicFixture) -> None:
    whatsapp = Bot(clinic, PHONE)
    await whatsapp.start()
    stop = await whatsapp.send("STOP")
    assert [r.kind for r in stop.replies] == ["opt_out"]
    assert (await whatsapp.send("hello")).replies == []

    voice = Bot(clinic, PHONE, channel=BotChannel.WEB_VOICE, lang_hint="en")
    silent = await voice.send("book an appointment")
    assert silent.ignored and silent.replies == []

    back = await whatsapp.send("START")
    assert [o for o, _ in whatsapp.options()] == ["menu:book", "menu:my", "menu:reception"]
    assert not back.ignored
    async with clinic.sessionmaker() as session:
        preference = await session.scalar(
            select(ContactPreference).where(ContactPreference.clinic_id == clinic.id)
        )
    assert preference is not None and preference.opted_out_at is None


@pytest.mark.parametrize(
    ("language", "message"),
    [
        ("en", "My father has chest pain and is sweating"),
        ("hi", "मेरी माँ बेहोश हो गई है"),
        ("te", "నాన్నకు ఛాతీ నొప్పి వస్తోంది"),
    ],
)
async def test_emergency_keywords_alert_staff(
    clinic: ClinicFixture, language: Language, message: str
) -> None:
    bot = Bot(clinic, PHONE)
    await bot.start(language)
    await bot.press("menu:reception")  # even while handed off
    result = await bot.send(message)
    assert [r.kind for r in result.replies] == ["emergency"]
    assert "108" in result.replies[0].text and "112" in result.replies[0].text
    assert result.replies[0].essential
    async with clinic.sessionmaker() as session:
        kinds = list(
            await session.scalars(select(BotAlert.kind).where(BotAlert.clinic_id == clinic.id))
        )
    assert "emergency" in kinds
    assert (await bot.conversation()).handoff_reason == "emergency"


@pytest.mark.parametrize(
    ("language", "message"),
    [
        ("en", "Which tablet should I take for fever?"),
        ("hi", "बुखार के लिए कौन सी दवा लूँ?"),
        ("te", "జ్వరానికి ఏ మందు వేసుకోవాలి?"),
    ],
)
async def test_medical_questions_are_refused(
    clinic: ClinicFixture, language: Language, message: str
) -> None:
    bot = Bot(clinic, PHONE)
    await bot.start(language)
    await bot.send(message)
    assert bot.texts()[0].startswith(t(language, "medical"))
    assert await _appointments(clinic) == []


async def test_stale_messages_are_recorded_but_ignored(clinic: ClinicFixture) -> None:
    bot = Bot(clinic, PHONE)
    now = datetime.combine(TODAY, time(8), tzinfo=IST)
    await bot.send("hello", sent_at=now)
    late = await bot.send("hello again", sent_at=now - timedelta(seconds=30))
    assert late.ignored and late.replies == []
    # A stale STOP still opts out.
    stop = await bot.send("stop", sent_at=now - timedelta(seconds=20))
    assert [r.kind for r in stop.replies] == ["opt_out"]


async def test_voice_simulator_starts_in_the_chosen_language(clinic: ClinicFixture) -> None:
    for index in range(4):
        await _doctor(clinic, name=f"Dr. Doctor {index}")
    bot = Bot(clinic, PHONE, channel=BotChannel.WEB_VOICE, lang_hint="hi")
    first = await bot.send("नमस्ते")
    assert t("hi", "menu") in first.replies[0].text
    await bot.press("menu:book")
    await bot.send("Ravi Kumar")
    # Spoken menus offer at most three choices: two doctors and "more".
    ids = [o for o, _ in bot.options()]
    assert len(ids) == 3 and ids[-1] == "more"
    await bot.send("तीन")  # "three" -> more
    assert len([o for o in (o for o, _ in bot.options()) if o.startswith("d:")]) == 2
