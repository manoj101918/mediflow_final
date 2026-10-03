"""Sending WhatsApp messages and downloading voice notes.

`PyWaSender` uses the direct Meta Cloud API through PyWa's async client (send-only; the
webhook is our own route). `FakeWhatsApp` records sends for tests and E2E (WHATSAPP_FAKE).
Only free-form (session) messages are built here: text, reply buttons and lists. There is
deliberately no template path, so nothing paid can be sent.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.services.conversation.types import (
    BUTTON_TITLE_MAX,
    MAX_BUTTONS,
    MAX_LIST_ROWS,
    ROW_DESCRIPTION_MAX,
    ROW_TITLE_MAX,
)
from app.services.messaging.dispatch import ChannelSender, SendError

BODY_MAX = 1024  # interactive message body
TEXT_MAX = 4096


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


@dataclass
class FakeWhatsApp:
    """Records every send; voice notes come from `media` (media id -> (bytes, mime))."""

    sent: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    media: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    deleted_media: list[str] = field(default_factory=list)
    fail_with: SendError | None = None

    async def send(self, phone_e164: str, body: dict[str, Any]) -> str:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append((phone_e164, body))
        return f"wamid.fake.{uuid.uuid4().hex}"

    async def download(self, media_id: str) -> tuple[bytes, str]:
        if media_id not in self.media:
            raise SendError("media not found", permanent=True)
        return self.media[media_id]


class PyWaSender:
    """Free-form messages through PyWa (direct Meta Cloud API)."""

    def __init__(self, phone_id: str, token: str, api_version: str | None) -> None:
        from pywa_async.client import WhatsApp  # noqa: PLC0415 - imported only when configured

        kwargs: dict[str, Any] = {"phone_id": phone_id, "token": token, "server": None}
        if api_version:
            kwargs["api_version"] = api_version.removeprefix("v")
        self._wa = WhatsApp(**kwargs)

    async def send(self, phone_e164: str, body: dict[str, Any]) -> str:
        from pywa.errors import WhatsAppError  # noqa: PLC0415
        from pywa.types.callback import Button, Section, SectionList, SectionRow  # noqa: PLC0415

        to = phone_e164.removeprefix("+")
        text = str(body.get("text", ""))
        buttons: Any = None
        if body.get("buttons"):
            buttons = [
                Button(title=_clip(b["title"], BUTTON_TITLE_MAX), callback_data=b["id"])
                for b in body["buttons"][:MAX_BUTTONS]
            ]
        elif body.get("rows"):
            rows = [
                SectionRow(
                    title=_clip(r["title"], ROW_TITLE_MAX),
                    callback_data=r["id"],
                    description=_clip(r["description"], ROW_DESCRIPTION_MAX)
                    if r.get("description")
                    else None,
                )
                for r in body["rows"][:MAX_LIST_ROWS]
            ]
            label = _clip(str(body.get("list_label") or "Choose"), BUTTON_TITLE_MAX)
            buttons = SectionList(button_title=label, sections=[Section(title=label, rows=rows)])
        limit = BODY_MAX if buttons is not None else TEXT_MAX
        try:
            sent = await self._wa.send_message(to=to, text=_clip(text, limit), buttons=buttons)
        except WhatsAppError as exc:
            # Meta flags transient errors; otherwise a 4xx (bad number, window closed, ...)
            # won't succeed on retry, while 429/5xx may.
            if exc.is_transient is not None:
                permanent = not exc.is_transient
            else:
                status = exc.raw_response.status_code if exc.raw_response is not None else 0
                permanent = 400 <= status < 500 and status != 429
            raise SendError(f"{type(exc).__name__} {exc.code}", permanent=permanent) from exc
        except Exception as exc:  # network errors: retry later
            raise SendError(type(exc).__name__) from exc
        return str(sent.id)

    async def download(self, media_id: str) -> tuple[bytes, str]:
        try:
            url = await self._wa.get_media_url(media_id)
            data = await self._wa.get_media_bytes(url=url.url)
        except Exception as exc:
            raise SendError(f"media download failed: {type(exc).__name__}") from exc
        return data, str(url.mime_type)


def _secret(value: Any) -> str | None:
    if value is None:
        return None
    secret = str(value.get_secret_value()).strip()
    return secret or None


_FAKE = FakeWhatsApp()


def fake_whatsapp() -> FakeWhatsApp:
    """The process-wide fake used when WHATSAPP_FAKE=true (E2E)."""
    return _FAKE


def build_sender(settings: Settings) -> ChannelSender | None:
    """The WhatsApp sender, or None when WhatsApp isn't configured (messages are blocked)."""
    if settings.whatsapp_fake:
        return _FAKE
    token = _secret(settings.whatsapp_access_token)
    if not (token and settings.whatsapp_phone_number_id):
        return None
    return PyWaSender(settings.whatsapp_phone_number_id, token, settings.whatsapp_api_version)


@dataclass(frozen=True)
class ConnectionInfo:
    """Result of a free Graph API read of the business phone number."""

    connected: bool
    display_phone_number: str | None = None
    verified_name: str | None = None
    error: str | None = None


_CONNECTION_TTL_SECONDS = 300
_connection_cache: dict[str, tuple[float, ConnectionInfo]] = {}


async def check_connection(settings: Settings) -> ConnectionInfo | None:
    """None when WhatsApp isn't configured; cached for 5 minutes."""
    import time  # noqa: PLC0415

    import httpx  # noqa: PLC0415
    from pywa.utils import Version  # noqa: PLC0415

    if settings.whatsapp_fake:
        return ConnectionInfo(connected=True, verified_name="Fake WhatsApp (WHATSAPP_FAKE)")
    token = _secret(settings.whatsapp_access_token)
    phone_id = settings.whatsapp_phone_number_id
    if not (token and phone_id):
        return None
    cached = _connection_cache.get(phone_id)
    if cached is not None and time.monotonic() - cached[0] < _CONNECTION_TTL_SECONDS:
        return cached[1]
    version = (settings.whatsapp_api_version or str(Version.GRAPH_API.value)).removeprefix("v")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"https://graph.facebook.com/v{version}/{phone_id}",
                params={"fields": "display_phone_number,verified_name"},
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code == 200:
            body = response.json()
            info = ConnectionInfo(
                connected=True,
                display_phone_number=body.get("display_phone_number"),
                verified_name=body.get("verified_name"),
            )
        else:
            message = (
                response.json().get("error", {}).get("message", "") if response.content else ""
            )
            info = ConnectionInfo(
                connected=False, error=f"HTTP {response.status_code}: {message}"[:300]
            )
    except httpx.HTTPError as exc:
        info = ConnectionInfo(connected=False, error=type(exc).__name__)
    _connection_cache[phone_id] = (time.monotonic(), info)
    return info
