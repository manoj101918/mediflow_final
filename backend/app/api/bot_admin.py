"""Admin: booking bot status (WhatsApp, webhook, free-tier usage) and keyword lists."""

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.errors import AppError
from app.deps import AdminUser, DbSession
from app.schemas.bot import (
    BotStatusOut,
    KeywordListIn,
    KeywordListOut,
    UsageOut,
    WhatsAppStatusOut,
)
from app.services import bot_status
from app.services.booking.timeutil import utcnow
from app.services.conversation.keywords import clean_words, keyword_lists, save_keyword_list
from app.services.whatsapp.client import check_connection

router = APIRouter(prefix="/admin/bot", tags=["admin"])


@router.get("/status")
async def status(session: DbSession, user: AdminUser) -> BotStatusOut:
    settings = get_settings()
    connection = await check_connection(settings)
    used = await bot_status.usage(session, user.clinic_id, settings, utcnow())
    base = (settings.public_base_url or "").rstrip("/")
    return BotStatusOut(
        whatsapp=WhatsAppStatusOut(
            configured=connection is not None,
            fake=settings.whatsapp_fake,
            connected=connection.connected if connection else None,
            display_phone_number=connection.display_phone_number if connection else None,
            verified_name=connection.verified_name if connection else None,
            error=connection.error if connection else None,
            webhook_url=f"{base}/api/whatsapp/webhook" if base else None,
            webhook_last_seen_at=await bot_status.webhook_last_seen(session, user.clinic_id),
            paid_templates_allowed=settings.whatsapp_allow_paid_templates,
        ),
        usage=UsageOut(
            month=used.month,
            sent=used.sent,
            limit=used.limit,
            reserve_from=used.reserve_from,
            warn=used.warn,
            exhausted=used.exhausted,
        ),
        llm_enabled=settings.bot_llm_enabled,
        stt_provider=settings.stt_provider,
        tts_provider=settings.tts_provider,
        clinic_configured=settings.inbound_clinic_id == user.clinic_id,
    )


@router.get("/keywords")
async def keywords(session: DbSession, user: AdminUser) -> list[KeywordListOut]:
    lists = await keyword_lists(session, user.clinic_id)
    return [
        KeywordListOut(kind=k.kind, language=k.language, words=k.words, custom=k.custom)
        for k in lists
    ]


@router.put("/keywords")
async def save_keywords(
    body: KeywordListIn, session: DbSession, user: AdminUser
) -> list[KeywordListOut]:
    if body.words is not None and body.kind == "emergency" and not clean_words(body.words):
        raise AppError(422, "VALIDATION", "Keep at least one emergency word.")
    await save_keyword_list(session, user.clinic_id, body.kind, body.language, body.words, user.id)
    return await keywords(session, user)
