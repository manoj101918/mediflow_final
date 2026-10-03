"""Dispatch settings and the WhatsApp sender, built from the app settings."""

from app.core.config import Settings, get_settings
from app.services.messaging.dispatch import DispatchDeps


def dispatch_deps(settings: Settings | None = None) -> DispatchDeps:
    from app.services.whatsapp.client import build_sender  # noqa: PLC0415 - avoids an import cycle

    current = settings or get_settings()
    return DispatchDeps(
        whatsapp=build_sender(current),
        free_limit=current.bot_free_reply_limit,
        essential_reserve=current.bot_essential_reserve,
        max_attempts=current.bot_max_attempts,
    )
