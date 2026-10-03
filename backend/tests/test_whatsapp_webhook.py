"""WhatsApp webhook: signatures, dedupe, ordering, delivery statuses, and a booking end to end."""

from typing import Any

from sqlalchemy import func, select, update

from app.db.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
    BotJob,
    BotUsageMonthly,
    ChannelMessage,
    ChannelMessageStatus,
    MessageDirection,
    MessageOutbox,
    OutboxStatus,
)
from app.services.messaging.dispatch import SendError
from tests.api_utils import TOMORROW
from tests.conftest import ClinicFixture
from tests.whatsapp_utils import SENDER, VERIFY, WhatsAppHarness, add_bot_doctor, envelope


async def _count(clinic: ClinicFixture, model: Any, *where: Any) -> int:
    async with clinic.sessionmaker() as session:
        count = await session.scalar(
            select(func.count()).select_from(model).where(model.clinic_id == clinic.id, *where)
        )
    return int(count or 0)


async def test_verification_challenge(wa: WhatsAppHarness) -> None:
    params = {"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "12345"}
    ok = await wa.client.get("/api/whatsapp/webhook", params=params)
    assert ok.status_code == 200 and ok.text == "12345"
    bad = await wa.client.get(
        "/api/whatsapp/webhook", params={**params, "hub.verify_token": "nope"}
    )
    assert bad.status_code == 403


async def test_invalid_signature_is_rejected_and_nothing_stored(wa: WhatsAppHarness) -> None:
    message = wa.message("text", wa.next_wamid(), 1, text={"body": "hi"})
    payload = envelope(messages=[message])
    assert await wa.post(payload, signature="sha256=" + "0" * 64) == 401
    assert await wa.post(payload, signature="garbage") == 401
    assert await _count(wa.clinic, ChannelMessage) == 0


async def test_first_message_gets_the_notice_once(wa: WhatsAppHarness) -> None:
    await wa.text("hello")
    assert await _count(wa.clinic, BotJob) == 1
    await wa.run()
    [(phone, body)] = wa.fake.sent
    assert phone == wa.phone
    assert [b["id"] for b in body["buttons"]] == ["lang:te", "lang:hi", "lang:en"]

    async with wa.clinic.sessionmaker() as session:
        outbox = (
            await session.scalars(
                select(MessageOutbox).where(MessageOutbox.clinic_id == wa.clinic.id)
            )
        ).one()
        usage = await session.scalar(
            select(BotUsageMonthly.sent_count).where(BotUsageMonthly.clinic_id == wa.clinic.id)
        )
        outbound = await session.scalar(
            select(ChannelMessage).where(
                ChannelMessage.clinic_id == wa.clinic.id,
                ChannelMessage.direction == MessageDirection.OUTBOUND,
            )
        )
    assert outbox.status is OutboxStatus.SENT and outbox.wamid is not None
    assert usage == 1
    assert outbound is not None and outbound.wamid == outbox.wamid


async def test_duplicate_wamid_is_processed_once(wa: WhatsAppHarness) -> None:
    wamid = wa.next_wamid()
    await wa.text("hello", wamid=wamid)
    await wa.text("hello", wamid=wamid)
    await wa.run()
    await wa.text("hello", wamid=wamid)  # redelivered after processing
    await wa.run()
    inbound = ChannelMessage.direction == MessageDirection.INBOUND
    assert await _count(wa.clinic, ChannelMessage, inbound) == 1
    assert len(wa.fake.sent) == 1


async def test_out_of_order_message_is_recorded_but_ignored(wa: WhatsAppHarness) -> None:
    newer = await wa.text("hello", ts=1_900_000_100)
    older = await wa.text("hello from before", ts=1_900_000_000)
    await wa.run()
    assert len(wa.fake.sent) == 1
    async with wa.clinic.sessionmaker() as session:
        rows = await session.execute(
            select(ChannelMessage.wamid, ChannelMessage.status).where(
                ChannelMessage.wamid.in_((newer, older))
            )
        )
        statuses = dict(rows.tuples().all())
    assert statuses == {
        newer: ChannelMessageStatus.PROCESSED,
        older: ChannelMessageStatus.IGNORED,
    }


async def test_delivery_statuses_never_move_backwards(wa: WhatsAppHarness) -> None:
    await wa.text("hello")
    await wa.run()
    async with wa.clinic.sessionmaker() as session:
        wamid = await session.scalar(
            select(MessageOutbox.wamid).where(MessageOutbox.clinic_id == wa.clinic.id)
        )
    assert wamid is not None

    for status in ("read", "delivered", "sent"):
        status_update = {"id": wamid, "status": status, "timestamp": "1", "recipient_id": SENDER}
        await wa.post(envelope(statuses=[status_update]))
    await wa.run()
    async with wa.clinic.sessionmaker() as session:
        outbox_status = await session.scalar(
            select(MessageOutbox.status).where(MessageOutbox.wamid == wamid)
        )
        message_status = await session.scalar(
            select(ChannelMessage.status).where(ChannelMessage.wamid == wamid)
        )
    assert outbox_status is OutboxStatus.READ
    assert message_status is ChannelMessageStatus.READ


async def test_status_before_its_message_is_retried(wa: WhatsAppHarness) -> None:
    status_update = {"id": "wamid.unknown", "status": "delivered", "timestamp": "1"}
    await wa.post(envelope(statuses=[status_update]))
    await wa.run()
    async with wa.clinic.sessionmaker() as session:
        job = await session.scalar(select(BotJob).where(BotJob.clinic_id == wa.clinic.id))
    assert job is not None and job.status.value == "pending" and job.attempts == 1


async def test_other_phone_numbers_are_ignored(wa: WhatsAppHarness) -> None:
    message = wa.message("text", wa.next_wamid(), 1, text={"body": "hi"})
    assert await wa.post(envelope(messages=[message], phone_id="SOMEONE_ELSE")) == 200
    assert await _count(wa.clinic, ChannelMessage) == 0


async def test_telugu_booking_with_buttons_only(wa: WhatsAppHarness) -> None:
    await add_bot_doctor(wa.clinic)
    await wa.say("నమస్కారం")
    await wa.choose("lang:te")
    await wa.choose("menu:book")
    await wa.say("Lakshmi Devi")
    for prefix in ("d:", f"day:{TOMORROW.isoformat()}", "t:", "r:general", "c:yes"):
        await wa.choose(prefix)

    async with wa.clinic.sessionmaker() as session:
        appointment = await session.scalar(
            select(Appointment).where(Appointment.clinic_id == wa.clinic.id)
        )
    assert appointment is not None
    assert appointment.status is AppointmentStatus.PENDING_CONFIRMATION
    assert appointment.source is AppointmentSource.WHATSAPP
    assert wa.last_body()["text"] == "అభ్యర్థన అందింది. రిసెప్షన్ త్వరలో నిర్ధారిస్తుంది."


async def test_a_failed_send_is_retried_and_delivered_once(wa: WhatsAppHarness) -> None:
    wa.fake.fail_with = SendError("network down")
    await wa.text("hello")
    await wa.run()
    assert wa.fake.sent == []
    async with wa.clinic.sessionmaker() as session:
        outbox = await session.scalar(
            select(MessageOutbox).where(MessageOutbox.clinic_id == wa.clinic.id)
        )
        retry = await session.scalar(
            select(BotJob).where(BotJob.clinic_id == wa.clinic.id, BotJob.kind == "outbox")
        )
    assert outbox is not None and outbox.status is OutboxStatus.PENDING
    assert retry is not None

    wa.fake.fail_with = None
    async with wa.clinic.sessionmaker() as session, session.begin():
        await session.execute(
            update(BotJob).where(BotJob.id == retry.id).values(run_after=func.now())
        )
    await wa.run()
    await wa.run()
    assert len(wa.fake.sent) == 1
