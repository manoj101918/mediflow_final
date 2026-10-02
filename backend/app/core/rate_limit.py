"""Request rate limiting (in-memory; one API process). Used for the public inbound endpoint."""

from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import get_settings
from app.core.errors import error_response

# Keyed by client IP and checked before the API key, so key guessing is throttled too.
limiter = Limiter(key_func=get_remote_address)


def inbound_rate_limit() -> str:
    """Read on every request so the limit follows configuration (and tests)."""
    return get_settings().inbound_rate_limit


async def _rate_limited(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RateLimitExceeded)  # noqa: S101
    retry_after = str(exc.limit.limit.get_expiry()) if exc.limit is not None else "60"
    return error_response(
        429,
        "RATE_LIMITED",
        "Too many requests. Slow down and retry later.",
        headers={"Retry-After": retry_after},
    )


# Patient chat: per signed-in user (not per IP), moving window, limit read per request.
_chat_storage = MemoryStorage()
_chat_limiter = MovingWindowRateLimiter(_chat_storage)


def allow_chat(user_id: UUID) -> bool:
    """Count one chat question for this user; False when over CHAT_RATE_LIMIT."""
    return _chat_limiter.hit(parse(get_settings().chat_rate_limit), "chat", str(user_id))


def reset_chat_limits() -> None:
    _chat_storage.reset()


def register_rate_limiting(app: FastAPI) -> None:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limited)
