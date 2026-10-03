"""Reception's bot inbox: handoffs, transcripts, replies, alerts; admin keyword lists."""

from datetime import timedelta

from sqlalchemy import update

from app.db.models import ChannelMessage, MessageDirection, UserRole
from app.services.booking.timeutil import utcnow
from tests.conftest import ClinicFixture, auth
from tests.whatsapp_utils import WhatsAppHarness, add_bot_doctor


async def _front_desk(clinic: ClinicFixture) -> dict[str, str]:
    return auth(await clinic.add_user(UserRole.RECEPTIONIST))


async def test_handoffs_are_listed_with_emergencies_first(wa: WhatsAppHarness) -> None:
    await wa.say("hello")
    await wa.choose("lang:en")
    await wa.choose("menu:reception")

    other = WhatsAppHarness(wa.client, wa.clinic, wa.fake, wa.deps, sender="919811100002")
    await other.say("hello")
    await other.choose("lang:te")
    await other.say("నాన్నకు గుండెపోటు వచ్చింది")

    headers = await _front_desk(wa.clinic)
    response = await wa.client.get("/api/bot/conversations", headers=headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert [r["phone"] for r in rows] == [other.phone, wa.phone]
    assert rows[0]["emergency"] is True and rows[0]["handoff_reason"] == "emergency"
    assert rows[1]["handoff_reason"] == "button" and rows[1]["window_open"] is True

    alerts = (await wa.client.get("/api/bot/alerts", headers=headers)).json()
    assert [a["kind"] for a in alerts] == ["emergency", "handoff"]
    assert alerts[0]["excerpt"] == "నాన్నకు గుండెపోటు వచ్చింది"

    ack = await wa.client.post(f"/api/bot/alerts/{alerts[0]['id']}/ack", headers=headers)
    assert ack.status_code == 204
    remaining = (await wa.client.get("/api/bot/alerts", headers=headers)).json()
    assert [a["kind"] for a in remaining] == ["handoff"]


async def test_reception_replies_and_resumes_the_bot(wa: WhatsAppHarness) -> None:
    await wa.say("hello")
    await wa.choose("lang:en")
    await wa.choose("menu:reception")
    headers = await _front_desk(wa.clinic)
    [conversation] = (await wa.client.get("/api/bot/conversations", headers=headers)).json()

    sent = await wa.client.post(
        f"/api/bot/conversations/{conversation['id']}/reply",
        json={"text": "Hello, this is reception. How can we help?"},
        headers=headers,
    )
    assert sent.status_code == 200 and sent.json() == {"status": "sent"}
    assert wa.last_body() == {"text": "Hello, this is reception. How can we help?"}

    await wa.say("I need a wheelchair at the entrance")  # bot paused: no reply
    assert wa.last_body()["text"] == "Hello, this is reception. How can we help?"

    detail = (
        await wa.client.get(f"/api/bot/conversations/{conversation['id']}", headers=headers)
    ).json()
    texts = [(m["direction"], m["text"]) for m in detail["messages"]]
    assert ("outbound", "Hello, this is reception. How can we help?") in texts
    assert ("inbound", "I need a wheelchair at the entrance") in texts

    resumed = await wa.client.post(
        f"/api/bot/conversations/{conversation['id']}/resume", headers=headers
    )
    assert resumed.status_code == 204
    assert (await wa.client.get("/api/bot/conversations", headers=headers)).json() == []
    await wa.say("thanks")
    assert [b["id"] for b in wa.last_body()["buttons"]] == [
        "menu:book",
        "menu:my",
        "menu:reception",
    ]


async def test_no_reply_outside_the_window_or_after_opt_out(wa: WhatsAppHarness) -> None:
    await wa.say("hello")
    await wa.choose("lang:en")
    await wa.choose("menu:reception")
    headers = await _front_desk(wa.clinic)
    [conversation] = (await wa.client.get("/api/bot/conversations", headers=headers)).json()
    url = f"/api/bot/conversations/{conversation['id']}/reply"

    async with wa.clinic.sessionmaker() as session, session.begin():
        await session.execute(
            update(ChannelMessage)
            .where(
                ChannelMessage.clinic_id == wa.clinic.id,
                ChannelMessage.direction == MessageDirection.INBOUND,
            )
            .values(created_at=utcnow() - timedelta(hours=25))
        )
    closed = await wa.client.post(url, json={"text": "Hi"}, headers=headers)
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "WINDOW_CLOSED"
    listed = (await wa.client.get("/api/bot/conversations", headers=headers)).json()
    assert listed[0]["window_open"] is False

    await wa.say("STOP")
    opted_out = await wa.client.post(url, json={"text": "Hi"}, headers=headers)
    assert opted_out.status_code == 409 and opted_out.json()["error"]["code"] == "OPTED_OUT"


async def test_view_chat_for_a_bot_booking(wa: WhatsAppHarness) -> None:
    await add_bot_doctor(wa.clinic)
    appointment_id = await wa.book()
    headers = await _front_desk(wa.clinic)
    found = await wa.client.get(
        f"/api/bot/appointments/{appointment_id}/conversation", headers=headers
    )
    conversation_id = found.json()["conversation_id"]
    assert conversation_id is not None
    detail = (
        await wa.client.get(f"/api/bot/conversations/{conversation_id}", headers=headers)
    ).json()
    assert detail["messages"][-1]["text"].startswith("Request received.")
    assert detail["names"] == ["Lakshmi"]


async def test_inbox_is_front_desk_only_and_clinic_scoped(
    wa: WhatsAppHarness, other_clinic: ClinicFixture
) -> None:
    await wa.say("hello")
    doctor = auth(await wa.clinic.add_user(UserRole.DOCTOR, link_doctor=True))
    assert (await wa.client.get("/api/bot/conversations", headers=doctor)).status_code == 403
    assert (await wa.client.get("/api/bot/alerts", headers=doctor)).status_code == 403

    mine = (
        await wa.client.get(
            "/api/bot/conversations?handoff=false", headers=await _front_desk(wa.clinic)
        )
    ).json()
    stranger = await _front_desk(other_clinic)
    response = await wa.client.get(f"/api/bot/conversations/{mine[0]['id']}", headers=stranger)
    assert response.status_code == 404


async def test_admin_edits_emergency_keywords(wa: WhatsAppHarness) -> None:
    admin = auth(await wa.clinic.add_user(UserRole.ADMIN))
    lists = (await wa.client.get("/api/admin/bot/keywords", headers=admin)).json()
    assert len(lists) == 9 and not any(item["custom"] for item in lists)

    saved = await wa.client.put(
        "/api/admin/bot/keywords",
        json={"kind": "emergency", "language": "en", "words": ["collapsed", " collapsed ", "fits"]},
        headers=admin,
    )
    assert saved.status_code == 200, saved.text
    english = next(i for i in saved.json() if i["kind"] == "emergency" and i["language"] == "en")
    assert english == {
        "kind": "emergency",
        "language": "en",
        "words": ["collapsed", "fits"],
        "custom": True,
    }

    await wa.say("hello")
    await wa.choose("lang:en")
    await wa.say("my mother collapsed")
    assert "108" in wa.last_body()["text"]

    empty = await wa.client.put(
        "/api/admin/bot/keywords",
        json={"kind": "emergency", "language": "en", "words": []},
        headers=admin,
    )
    assert empty.status_code == 422
    restored = await wa.client.put(
        "/api/admin/bot/keywords",
        json={"kind": "emergency", "language": "en", "words": None},
        headers=admin,
    )
    english = next(i for i in restored.json() if i["kind"] == "emergency" and i["language"] == "en")
    assert english["custom"] is False and "chest pain" in english["words"]
    receptionist = await _front_desk(wa.clinic)
    assert (await wa.client.get("/api/admin/bot/keywords", headers=receptionist)).status_code == 403
