"""A fake Meta: signed webhook posts in, a FakeWhatsApp sender out, the bot worker in between."""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import time
from typing import Any
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import Appointment
from app.services.bot_jobs.worker import BotDeps, run_pending
from app.services.conversation.intent import RuleParser
from app.services.messaging.dispatch import DispatchDeps
from app.services.speech.stt import FakeSTT
from app.services.whatsapp.client import FakeWhatsApp
from app.services.whatsapp.voice import voice_normalizer
from tests.api_utils import EVERY_DAY, TOMORROW
from tests.conftest import ClinicFixture

SECRET = "pytest-app-secret"
VERIFY = "pytest-verify-token"
PHONE_ID = "PYTEST_PHONE_ID"
SENDER = "919811100001"
PHONE = f"+{SENDER}"

_LIST_PREFIXES = ("d:", "day:", "t:", "r:", "p:", "a:")


def envelope(
    *,
    messages: list[dict[str, Any]] | None = None,
    statuses: list[dict[str, Any]] | None = None,
    phone_id: str = PHONE_ID,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": phone_id},
    }
    if messages:
        value["messages"] = messages
        value["contacts"] = [{"wa_id": messages[0]["from"], "profile": {"name": "Test"}}]
    if statuses:
        value["statuses"] = statuses
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": value}]}],
    }


def bot_deps(fake: FakeWhatsApp, *, free_limit: int = 1000, reserve: int = 100) -> BotDeps:
    return BotDeps(
        dispatch=DispatchDeps(whatsapp=fake, free_limit=free_limit, essential_reserve=reserve),
        notice_version="pytest",
        max_attempts=5,
        normalize=voice_normalizer(fake, FakeSTT()),
        understand=RuleParser(),
    )


@dataclass
class WhatsAppHarness:
    client: AsyncClient
    clinic: ClinicFixture
    fake: FakeWhatsApp
    deps: BotDeps
    sender: str = SENDER
    _seq: int = 0

    @property
    def phone(self) -> str:
        return f"+{self.sender}"

    async def post(self, payload: dict[str, Any], *, signature: str | None = None) -> int:
        body = json.dumps(payload).encode()
        sig = signature or "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        response = await self.client.post(
            "/api/whatsapp/webhook",
            content=body,
            headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
        )
        return response.status_code

    def next_wamid(self) -> str:
        self._seq += 1
        return f"wamid.pytest.{self.clinic.id.hex[:8]}.{self.sender[-4:]}.{self._seq}"

    def message(self, kind: str, wamid: str, ts: int, **content: Any) -> dict[str, Any]:
        return {"from": self.sender, "id": wamid, "timestamp": str(ts), "type": kind, **content}

    async def text(self, body: str, *, wamid: str | None = None, ts: int = 1_900_000_000) -> str:
        wamid = wamid or self.next_wamid()
        await self.post(envelope(messages=[self.message("text", wamid, ts, text={"body": body})]))
        return wamid

    async def voice(self, media_id: str, *, ts: int = 1_900_000_000) -> str:
        wamid = self.next_wamid()
        audio = {"id": media_id, "mime_type": "audio/ogg; codecs=opus", "voice": True}
        await self.post(envelope(messages=[self.message("audio", wamid, ts, audio=audio)]))
        return wamid

    async def press(self, reply_id: str, title: str = "x", *, ts: int = 1_900_000_000) -> str:
        wamid = self.next_wamid()
        kind = "list_reply" if reply_id.startswith(_LIST_PREFIXES) else "button_reply"
        interactive = {"type": kind, kind: {"id": reply_id, "title": title}}
        await self.post(
            envelope(messages=[self.message("interactive", wamid, ts, interactive=interactive)])
        )
        return wamid

    async def run(self) -> int:
        return await run_pending(self.clinic.sessionmaker, self.deps, clinic_id=self.clinic.id)

    def last_body(self) -> dict[str, Any]:
        return self.fake.sent[-1][1]

    def option(self, prefix: str) -> str:
        body = self.last_body()
        for option in (*body.get("buttons", []), *body.get("rows", [])):
            if option["id"].startswith(prefix):
                return str(option["id"])
        raise AssertionError(f"no option {prefix!r} in {body}")

    async def say(self, text: str) -> None:
        await self.text(text)
        await self.run()

    async def choose(self, prefix: str) -> None:
        await self.press(self.option(prefix))
        await self.run()

    async def book(self, language: str = "en", *, name: str = "Lakshmi Devi") -> UUID:
        """Book tomorrow's first free slot with buttons only; returns the appointment id."""
        await self.say("hello")
        await self.choose(f"lang:{language}")
        await self.choose("menu:book")
        body = self.last_body()
        if any(row["id"] == "p:new" for row in body.get("rows", [])):
            await self.choose("p:new")
        await self.say(name)
        for prefix in ("d:", f"day:{TOMORROW.isoformat()}", "t:", "r:general", "c:yes"):
            await self.choose(prefix)
        async with self.clinic.sessionmaker() as session:
            appointment_id = await session.scalar(
                select(Appointment.id)
                .where(Appointment.clinic_id == self.clinic.id)
                .order_by(Appointment.created_at.desc())
                .limit(1)
            )
        assert appointment_id is not None
        return appointment_id


async def add_bot_doctor(clinic: ClinicFixture, name: str = "Dr. Anil Sharma") -> UUID:
    return await clinic.add_doctor(name=name, windows=((time(9), time(11)),), weekdays=EVERY_DAY)
