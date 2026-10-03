"""Drive the booking conversation like a patient would (real database, real clock)."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import BotChannel, BotConversation, MessageOutbox
from app.services.conversation import InboundMsg, TurnResult, run_turn
from app.services.conversation.types import Language
from tests.conftest import ClinicFixture

NOTICE_VERSION = "pytest"


@dataclass
class Bot:
    clinic: ClinicFixture
    phone: str = "+919811100001"
    channel: BotChannel = BotChannel.WHATSAPP
    lang_hint: Language | None = None
    last: TurnResult | None = None
    history: list[TurnResult] = field(default_factory=list)

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        return self.clinic.sessionmaker

    async def _store(self, kind: str, body: str) -> UUID:
        """Insert the inbound message as the webhook would (status received)."""
        message_id = uuid.uuid4()
        async with self.sessionmaker() as session, session.begin():
            await session.execute(
                text(
                    "insert into public.channel_messages (id, clinic_id, direction, channel, "
                    "phone_e164, type, body_text, status) values (:id, :cid, 'inbound', "
                    "cast(:channel as public.bot_channel), :phone, :type, :body, 'received')"
                ),
                {
                    "id": message_id,
                    "cid": self.clinic.id,
                    "channel": self.channel.value,
                    "phone": self.phone,
                    "type": kind,
                    "body": body,
                },
            )
        return message_id

    async def send(
        self,
        message: str = "",
        *,
        reply: str | None = None,
        kind: str | None = None,
        sent_at: datetime | None = None,
        now: datetime | None = None,
        extras: dict[str, Any] | None = None,
    ) -> TurnResult:
        msg_kind = kind or ("reply" if reply is not None else "text")
        title = message
        if reply is not None and not message:
            title = self.title_of(reply)
        message_id = await self._store(msg_kind, title)
        msg = InboundMsg(
            channel=self.channel,
            phone_e164=self.phone,
            kind=msg_kind,  # type: ignore[arg-type]
            text=title,
            reply_id=reply,
            lang_hint=self.lang_hint,
            message_id=message_id,
            external_id=f"wamid.{message_id.hex}",
            sent_at=sent_at,
        )
        async with self.sessionmaker() as session:
            result = await run_turn(
                session,
                self.clinic.id,
                msg,
                notice_version=NOTICE_VERSION,
                now=now,
                extras=extras,
            )
        self.last = result
        self.history.append(result)
        return result

    async def press(self, prefix: str) -> TurnResult:
        """Choose the (first) offered option whose id starts with `prefix`."""
        return await self.send(reply=self.option_id(prefix))

    def options(self) -> list[tuple[str, str]]:
        assert self.last is not None
        found: list[tuple[str, str]] = []
        for reply in self.last.replies:
            found += [(o.id, o.title) for o in (*reply.buttons, *reply.rows)]
        return found

    def option_id(self, prefix: str) -> str:
        for option_id, _ in self.options():
            if option_id.startswith(prefix):
                return option_id
        raise AssertionError(f"no option {prefix!r} in {self.options()}")

    def title_of(self, option_id: str) -> str:
        return dict(self.options()).get(option_id, option_id)

    def texts(self) -> list[str]:
        assert self.last is not None
        return [r.text for r in self.last.replies]

    async def conversation(self) -> BotConversation:
        async with self.sessionmaker() as session:
            row = await session.scalar(
                select(BotConversation).where(
                    BotConversation.clinic_id == self.clinic.id,
                    BotConversation.channel == self.channel,
                    BotConversation.phone_e164 == self.phone,
                )
            )
            assert row is not None
            return row

    async def outbox(self) -> list[MessageOutbox]:
        async with self.sessionmaker() as session:
            rows = await session.scalars(
                select(MessageOutbox)
                .where(MessageOutbox.clinic_id == self.clinic.id)
                .order_by(MessageOutbox.created_at)
            )
            return list(rows)

    async def start(self, language: Language = "en") -> None:
        """Say hello and pick a language: ends at the main menu."""
        await self.send("hello")
        if self.lang_hint is None:
            await self.press(f"lang:{language}")
