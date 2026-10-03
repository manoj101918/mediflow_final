"""Meta WhatsApp Cloud API webhook.

GET answers Meta's verification challenge. POST checks X-Hub-Signature-256 (HMAC-SHA256 of
the raw body with the app secret), stores every message once (unique wamid) with a job for the
bot worker, queues delivery statuses, and returns 200 straight away. Processing happens in the
worker, so a slow LLM or speech-to-text call never makes Meta retry the webhook.
"""

import hashlib
import hmac
import json
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import (
    BotChannel,
    ChannelMessage,
    ChannelMessageStatus,
    MessageDirection,
)
from app.deps import DbSession
from app.services.bot_jobs import queue
from app.services.whatsapp.parse import parse_webhook

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

MAX_BODY_BYTES = 1_000_000


def signature_valid(body: bytes, header: str | None, secret: str) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def _secret(value: Any) -> str | None:
    if value is None:
        return None
    secret = str(value.get_secret_value()).strip()
    return secret or None


@router.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> str:
    expected = _secret(get_settings().whatsapp_verify_token)
    if expected is None:
        raise AppError(503, "NOT_CONFIGURED", "WhatsApp is not configured on this server.")
    if mode != "subscribe" or token is None or not hmac.compare_digest(token, expected):
        raise AppError(403, "FORBIDDEN", "Verification failed.")
    return challenge or ""


@router.post("/webhook")
async def receive_webhook(request: Request, session: DbSession) -> dict[str, bool]:
    settings = get_settings()
    secret = _secret(settings.whatsapp_app_secret)
    clinic_id = settings.inbound_clinic_id
    if secret is None or clinic_id is None:
        raise AppError(503, "NOT_CONFIGURED", "WhatsApp is not configured on this server.")

    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise AppError(413, "PAYLOAD_TOO_LARGE", "Webhook payload is too large.")
    if not signature_valid(body, request.headers.get("X-Hub-Signature-256"), secret):
        raise AppError(401, "INVALID_SIGNATURE", "Invalid webhook signature.")
    try:
        payload = json.loads(body)
    except ValueError:
        raise AppError(400, "INVALID_JSON", "Webhook body is not JSON.") from None
    if not isinstance(payload, dict):
        raise AppError(400, "INVALID_JSON", "Webhook body is not a JSON object.")

    batch = parse_webhook(payload, settings.whatsapp_phone_number_id)
    for message in batch.messages:
        stored = await session.scalar(
            insert(ChannelMessage)
            .values(
                clinic_id=clinic_id,
                direction=MessageDirection.INBOUND,
                channel=BotChannel.WHATSAPP,
                phone_e164=message.phone_e164,
                wamid=message.wamid,
                type=message.type,
                payload=message.raw,
                body_text=message.text or None,
                status=ChannelMessageStatus.RECEIVED,
                message_ts=message.sent_at,
            )
            .on_conflict_do_nothing(
                index_elements=["wamid"], index_where=ChannelMessage.wamid.isnot(None)
            )
            .returning(ChannelMessage.id)
        )
        if stored is not None:  # a redelivered wamid is ignored
            await queue.enqueue(session, clinic_id, "inbound", ref_id=stored)
    for status in batch.statuses:
        await queue.enqueue(
            session,
            clinic_id,
            "status",
            payload={"wamid": status.wamid, "status": status.status, "error": status.error},
        )
    await session.commit()
    return {"ok": True}
