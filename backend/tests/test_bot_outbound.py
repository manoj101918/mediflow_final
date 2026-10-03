"""Outbound bot messages: approval/rejection, opt-out, the 24 h window, the free-tier meter."""

from datetime import timedelta

from sqlalchemy import func, select, update

from app.db.models import (
    Appointment,
    AppointmentStatus,
    BotUsageMonthly,
    ChannelMessage,
    MessageDirection,
    MessageOutbox,
    OutboxStatus,
    UserRole,
)
from app.services.booking.timeutil import utcnow
from app.services.messaging.notify import notify_decision
from tests.conftest import auth
from tests.whatsapp_utils import WhatsAppHarness, add_bot_doctor, bot_deps


async def _receptionist(wa: WhatsAppHarness) -> dict[str, str]:
    return auth(await wa.clinic.add_user(UserRole.RECEPTIONIST))


async def _outbox(wa: WhatsAppHarness, kind: str) -> list[MessageOutbox]:
    async with wa.clinic.sessionmaker() as session:
        rows = await session.scalars(
            select(MessageOutbox).where(
                MessageOutbox.clinic_id == wa.clinic.id, MessageOutbox.kind == kind
            )
        )
        return list(rows)


async def test_approve_sends_exactly_one_confirmation(wa: WhatsAppHarness) -> None:
    await add_bot_doctor(wa.clinic)
    appointment_id = await wa.book("hi")
    headers = await _receptionist(wa)

    response = await wa.client.post(f"/api/appointments/{appointment_id}/approve", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "scheduled"
    assert body["notification"] == {"status": "queued", "channel": "whatsapp", "phone": wa.phone}

    sent_before = len(wa.fake.sent)
    await wa.run()
    assert len(wa.fake.sent) == sent_before + 1
    text = wa.last_body()["text"]
    assert text.startswith("आपका अपॉइंटमेंट पक्का हो गया है।")
    assert f"टोकन नंबर: {body['token_number']}" in text

    again = await wa.client.post(f"/api/appointments/{appointment_id}/approve", headers=headers)
    assert again.status_code == 409
    async with wa.clinic.sessionmaker() as session:
        repeat = await notify_decision(
            session, wa.clinic.id, appointment_id, "approval", wa.deps.dispatch
        )
    assert repeat is not None
    await wa.run()
    assert len(wa.fake.sent) == sent_before + 1
    assert len(await _outbox(wa, "approval")) == 1


async def test_reject_offers_alternatives_and_continues_the_booking(wa: WhatsAppHarness) -> None:
    await add_bot_doctor(wa.clinic)
    appointment_id = await wa.book("en")
    headers = await _receptionist(wa)

    response = await wa.client.post(
        f"/api/appointments/{appointment_id}/reject",
        json={"reason": "Doctor busy"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["notification"]["status"] == "queued"
    await wa.run()
    rejection = wa.last_body()
    assert rejection["text"].startswith("Sorry, reception couldn't confirm")
    assert 1 <= len(rejection["rows"]) <= 3

    await wa.choose("t:")
    await wa.choose("r:skip")
    await wa.choose("c:yes")
    async with wa.clinic.sessionmaker() as session:
        statuses = list(
            await session.scalars(
                select(Appointment.status)
                .where(Appointment.clinic_id == wa.clinic.id)
                .order_by(Appointment.created_at)
            )
        )
    assert statuses == [AppointmentStatus.CANCELLED, AppointmentStatus.PENDING_CONFIRMATION]


async def test_nothing_is_sent_to_opted_out_numbers(wa: WhatsAppHarness) -> None:
    await add_bot_doctor(wa.clinic)
    appointment_id = await wa.book()
    await wa.say("STOP")
    assert wa.last_body()["text"].startswith("You have been unsubscribed")
    sent_before = len(wa.fake.sent)

    response = await wa.client.post(
        f"/api/appointments/{appointment_id}/approve", headers=await _receptionist(wa)
    )
    assert response.json()["notification"]["status"] == "opted_out"
    await wa.run()
    await wa.say("hello")
    assert len(wa.fake.sent) == sent_before
    [approval] = await _outbox(wa, "approval")
    assert (approval.status, approval.blocked_reason) == (OutboxStatus.BLOCKED, "opted_out")


async def test_nothing_is_sent_outside_the_24h_window(wa: WhatsAppHarness) -> None:
    await add_bot_doctor(wa.clinic)
    appointment_id = await wa.book()
    async with wa.clinic.sessionmaker() as session, session.begin():
        await session.execute(
            update(ChannelMessage)
            .where(
                ChannelMessage.clinic_id == wa.clinic.id,
                ChannelMessage.direction == MessageDirection.INBOUND,
            )
            .values(created_at=utcnow() - timedelta(hours=25))
        )
    sent_before = len(wa.fake.sent)

    response = await wa.client.post(
        f"/api/appointments/{appointment_id}/approve", headers=await _receptionist(wa)
    )
    assert response.json()["notification"]["status"] == "window_closed"
    await wa.run()
    assert len(wa.fake.sent) == sent_before
    [approval] = await _outbox(wa, "approval")
    assert approval.blocked_reason == "window_closed"


async def test_free_tier_limit_keeps_a_reserve_for_essential_messages(
    wa: WhatsAppHarness,
) -> None:
    # Limit 3, reserve 1: ordinary replies stop after 2; essential ones may use the third.
    wa.deps = bot_deps(wa.fake, free_limit=3, reserve=1)
    await wa.say("hello")  # notice: 1
    await wa.choose("lang:en")  # menu: 2
    await wa.choose("menu:book")  # ordinary reply: blocked (limit)
    assert len(wa.fake.sent) == 2
    await wa.say("my father has chest pain")  # essential: 3
    assert len(wa.fake.sent) == 3
    assert "108" in wa.last_body()["text"]
    await wa.say("help, he is unconscious")  # essential, but the allowance is used up
    assert len(wa.fake.sent) == 3

    async with wa.clinic.sessionmaker() as session:
        usage = await session.scalar(
            select(BotUsageMonthly.sent_count).where(BotUsageMonthly.clinic_id == wa.clinic.id)
        )
        blocked = await session.scalar(
            select(func.count())
            .select_from(MessageOutbox)
            .where(
                MessageOutbox.clinic_id == wa.clinic.id,
                MessageOutbox.blocked_reason == "limit",
            )
        )
    assert usage == len(wa.fake.sent) == 3  # the meter matches what was actually sent
    assert blocked is not None and blocked >= 2


async def test_staff_bookings_get_no_bot_message(wa: WhatsAppHarness) -> None:
    doctor = await add_bot_doctor(wa.clinic)
    patient = await wa.clinic.add_patient("Walk In", "+919800000077")
    appointment = await wa.clinic.add_appointment(doctor, patient, status="pending_confirmation")
    async with wa.clinic.sessionmaker() as session:
        result = await notify_decision(
            session, wa.clinic.id, appointment, "approval", wa.deps.dispatch
        )
    assert result is None


async def test_admin_sees_usage_and_status(wa: WhatsAppHarness) -> None:
    await wa.say("hello")
    admin = auth(await wa.clinic.add_user(UserRole.ADMIN))
    response = await wa.client.get("/api/admin/bot/status", headers=admin)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["usage"]["sent"] == 1
    assert body["usage"]["warn"] is False
    assert body["whatsapp"]["webhook_last_seen_at"] is not None
    assert body["clinic_configured"] is True
    receptionist = await wa.client.get("/api/admin/bot/status", headers=await _receptionist(wa))
    assert receptionist.status_code == 403
