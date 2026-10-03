"""Voice booking simulator: fake STT/TTS, a real booking, approval reaches the simulator."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.api.voice_sim import SpeechProviders, get_speech_providers
from app.db.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
    ChannelMessage,
    UserRole,
)
from app.deps import get_dispatch_deps
from app.services.bot_jobs.worker import run_pending
from app.services.conversation.i18n import t
from app.services.conversation.types import Option, Reply
from app.services.conversation.voice_style import speakable
from app.services.speech.stt import FakeSTT
from app.services.speech.tts import FakeTTS
from app.services.whatsapp.client import FakeWhatsApp
from tests.api_utils import TOMORROW
from tests.conftest import ClinicFixture, auth
from tests.whatsapp_utils import add_bot_doctor, bot_deps

CALLER = "9811100009"


class Simulator:
    def __init__(self, client: AsyncClient, headers: dict[str, str], language: str) -> None:
        self.client, self.headers, self.language = client, headers, language
        self.last: dict[str, Any] = {}

    async def _turn(self, **form: str) -> dict[str, Any]:
        files = None
        if "audio" in form:
            files = {"audio": ("rec.webm", form.pop("audio").encode(), "audio/webm")}
        response = await self.client.post(
            "/api/admin/voice-sim/turn",
            data={"phone": CALLER, "language": self.language, **form},
            files=files,
            headers=self.headers,
        )
        assert response.status_code == 200, response.text
        self.last = response.json()
        return self.last

    async def speak(self, words: str) -> dict[str, Any]:
        return await self._turn(audio=words)

    async def tap(self, prefix: str) -> dict[str, Any]:
        for reply in self.last["replies"]:
            for option in reply["options"]:
                if option["id"].startswith(prefix):
                    return await self._turn(reply_id=option["id"])
        raise AssertionError(f"no option {prefix!r} in {self.last['replies']}")


@pytest.fixture
async def sim(app: FastAPI, client: AsyncClient, clinic: ClinicFixture) -> AsyncIterator[Simulator]:
    deps = bot_deps(FakeWhatsApp())
    app.dependency_overrides[get_speech_providers] = lambda: SpeechProviders(FakeSTT(), FakeTTS())
    app.dependency_overrides[get_dispatch_deps] = lambda: deps.dispatch
    yield Simulator(client, auth(await clinic.add_user(UserRole.ADMIN)), "hi")


async def test_simulator_books_and_hears_the_approval(
    sim: Simulator, clinic: ClinicFixture
) -> None:
    await add_bot_doctor(clinic)
    first = await sim.speak("नमस्ते")
    assert first["transcript"] == "नमस्ते"
    assert t("hi", "menu") in first["speech_text"]
    assert "1 बोलें" in first["speech_text"]  # options are read out as numbers

    await sim.speak("अपॉइंटमेंट बुक करना है")
    assert sim.last["replies"][0]["text"] == t("hi", "ask_name")
    await sim.speak("Ravi Kumar")
    await sim.speak("एक")  # first doctor
    await sim.tap(f"day:{TOMORROW.isoformat()}")
    await sim.speak("एक")  # first time
    await sim.tap("r:general")
    assert "डॉक्टर: Dr. Anil Sharma" in sim.last["speech_text"]  # read-back before confirming
    done = await sim.speak("हाँ")
    assert done["replies"][0]["text"] == t("hi", "requested")
    assert done["appointment_id"] is not None

    async with clinic.sessionmaker() as session:
        appointment = await session.get(Appointment, done["appointment_id"])
        recording = await session.scalar(
            select(ChannelMessage)
            .where(ChannelMessage.clinic_id == clinic.id, ChannelMessage.type == "audio")
            .order_by(ChannelMessage.created_at)
            .limit(1)
        )
    assert appointment is not None
    assert (appointment.status, appointment.source) == (
        AppointmentStatus.PENDING_CONFIRMATION,
        AppointmentSource.VOICE,
    )
    assert recording is not None and recording.transcript == "नमस्ते" and recording.payload == {}

    reception = auth(await clinic.add_user(UserRole.RECEPTIONIST))
    approved = await sim.client.post(
        f"/api/appointments/{appointment.id}/approve", headers=reception
    )
    assert approved.json()["notification"]["channel"] == "web_voice"
    await run_pending(clinic.sessionmaker, bot_deps(FakeWhatsApp()), clinic_id=clinic.id)
    messages = (
        await sim.client.get(
            "/api/admin/voice-sim/messages", params={"phone": CALLER}, headers=sim.headers
        )
    ).json()
    assert messages[0]["kind"] == "approval" and messages[0]["status"] == "sent"
    assert f"टोकन नंबर: {appointment.token_number}" in messages[0]["text"]


async def test_bad_recordings_and_reset(sim: Simulator, clinic: ClinicFixture) -> None:
    await sim.speak("hello")
    too_long = await sim.speak("TOO_LONG")
    assert too_long["voice_error"] == "too_long"
    assert too_long["replies"][0]["text"] == t("hi", "voice_too_long")

    reset = await sim.client.post(
        "/api/admin/voice-sim/reset", json={"phone": CALLER}, headers=sim.headers
    )
    assert reset.status_code == 204
    again = await sim.speak("hello")
    assert t("hi", "menu") in again["speech_text"]  # a fresh conversation: notice + menu


async def test_simulator_is_admin_only(sim: Simulator, clinic: ClinicFixture) -> None:
    reception = auth(await clinic.add_user(UserRole.RECEPTIONIST))
    response = await sim.client.post(
        "/api/admin/voice-sim/turn",
        data={"phone": CALLER, "language": "en", "text": "hi"},
        headers=reception,
    )
    assert response.status_code == 403
    empty = await sim.client.post(
        "/api/admin/voice-sim/turn",
        data={"phone": CALLER, "language": "en"},
        headers=sim.headers,
    )
    assert empty.status_code == 422


def test_spoken_prompt_numbers_options_and_reads_back() -> None:
    reply = Reply(
        text="Please confirm:\nDoctor: Dr. Anil Sharma\nTime: 10:15 AM",
        buttons=(Option("c:yes", "Confirm"), Option("c:change", "Change")),
    )
    spoken = speakable([reply], "en")
    assert spoken == (
        "Please confirm: Doctor: Dr. Anil Sharma. Time: 10:15 AM. "
        "Say 1 for Confirm. Say 2 for Change."
    )
