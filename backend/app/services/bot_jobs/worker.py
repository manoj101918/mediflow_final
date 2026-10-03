"""The bot worker: runs conversation turns for stored inbound messages and sends replies.

The webhook only stores messages and enqueues jobs; everything slow (speech-to-text, the
LLM, the booking service, Meta's API) happens here. Logs carry ids only, never message text.
"""

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.models import ChannelMessage, ChannelMessageStatus
from app.services.booking.timeutil import utcnow
from app.services.bot_jobs import queue
from app.services.conversation import run_turn
from app.services.conversation.intent import Understander, build_understander
from app.services.messaging.dispatch import (
    DispatchDeps,
    SendError,
    apply_status,
    dispatch,
)
from app.services.whatsapp.voice import Normalizer, build_normalizer, plain_normalizer

logger = structlog.get_logger(__name__)


class StatusNotReadyError(RuntimeError):
    """A delivery status arrived before the message it refers to was recorded."""


@dataclass(frozen=True)
class BotDeps:
    dispatch: DispatchDeps
    notice_version: str
    max_attempts: int
    normalize: Normalizer = plain_normalizer
    # Free text / transcripts -> intents (rules or the LLM); None = menus only.
    understand: Understander | None = None
    extras: dict[str, Any] = field(default_factory=dict)


async def send_now(
    sessionmaker: async_sessionmaker[AsyncSession],
    deps: BotDeps,
    clinic_id: UUID,
    outbox_ids: list[UUID],
) -> None:
    """Send freshly queued replies; anything that fails is retried by an `outbox` job.

    The turn is already committed (its message is processed), so a failure here must not
    fail the inbound job: the reply would never be retried.
    """
    for outbox_id in outbox_ids:
        try:
            async with sessionmaker() as session:
                await dispatch(session, deps.dispatch, outbox_id, utcnow())
        except Exception as exc:
            if not isinstance(exc, SendError):
                logger.warning(
                    "bot_send_failed", outbox_id=str(outbox_id), error_type=type(exc).__name__
                )
            async with sessionmaker() as session:
                await queue.enqueue(session, clinic_id, "outbox", ref_id=outbox_id)
                await session.commit()


async def _inbound(
    sessionmaker: async_sessionmaker[AsyncSession], deps: BotDeps, job: queue.ClaimedJob
) -> str | None:
    async with sessionmaker() as session:
        message = await session.get(ChannelMessage, job.ref_id)
        if message is None or message.status is not ChannelMessageStatus.RECEIVED:
            return "already handled"
        msg = await deps.normalize(session, message)
        result = await run_turn(
            session,
            job.clinic_id,
            msg,
            notice_version=deps.notice_version,
            extras=deps.extras,
            understand=deps.understand,
        )
    await send_now(sessionmaker, deps, job.clinic_id, result.outbox_ids)
    return None


async def _status(
    sessionmaker: async_sessionmaker[AsyncSession], _: BotDeps, job: queue.ClaimedJob
) -> str | None:
    payload = job.payload
    async with sessionmaker() as session:
        found = await apply_status(
            session, str(payload["wamid"]), str(payload["status"]), payload.get("error")
        )
    if not found:
        raise StatusNotReadyError(str(payload["wamid"]))
    return None


async def _outbox(
    sessionmaker: async_sessionmaker[AsyncSession], deps: BotDeps, job: queue.ClaimedJob
) -> str | None:
    assert job.ref_id is not None  # noqa: S101 - outbox jobs always reference a row
    async with sessionmaker() as session:
        await dispatch(session, deps.dispatch, job.ref_id, utcnow())
    return None


_HANDLERS = {"inbound": _inbound, "status": _status, "outbox": _outbox}


async def process_job(
    sessionmaker: async_sessionmaker[AsyncSession], deps: BotDeps, job: queue.ClaimedJob
) -> None:
    try:
        note = await _HANDLERS[job.kind](sessionmaker, deps, job)
    except Exception as exc:
        logger.warning(
            "bot_job_failed", job_id=str(job.id), kind=job.kind, error_type=type(exc).__name__
        )
        async with sessionmaker() as session:
            await queue.mark_failed(session, job, type(exc).__name__, deps.max_attempts)
        return
    async with sessionmaker() as session:
        await queue.mark_done(session, job.id, note)


async def run_pending(
    sessionmaker: async_sessionmaker[AsyncSession],
    deps: BotDeps,
    *,
    clinic_id: UUID | None = None,
    max_jobs: int = 10_000,
) -> int:
    """Process due jobs until none are left (with clinic_id: only that clinic's)."""
    done = 0
    while done < max_jobs:
        async with sessionmaker() as session:
            job = await queue.claim_next(session, clinic_id=clinic_id)
        if job is None:
            return done
        await process_job(sessionmaker, deps, job)
        done += 1
    return done


def default_deps(settings: Settings | None = None) -> BotDeps:
    from app.services.whatsapp.client import build_sender  # noqa: PLC0415 - optional SDK

    current = settings or get_settings()
    return BotDeps(
        dispatch=DispatchDeps(
            whatsapp=build_sender(current),
            free_limit=current.bot_free_reply_limit,
            essential_reserve=current.bot_essential_reserve,
            max_attempts=current.bot_max_attempts,
        ),
        notice_version=current.bot_notice_version,
        max_attempts=current.bot_max_attempts,
        normalize=build_normalizer(current),
        understand=build_understander(current),
    )


class BotWorker:
    """The background loop. start() is idempotent; stop() cancels and waits."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        poll_seconds: float,
        *,
        deps_factory: Callable[[], BotDeps] = default_deps,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._poll = poll_seconds
        self._deps_factory = deps_factory
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if not self.running:
            self._task = asyncio.create_task(self._loop(), name="bot-worker")
            logger.info("bot_worker_started")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("bot_worker_stopped")

    async def _loop(self) -> None:
        deps = self._deps_factory()
        while True:
            try:
                ran = await run_pending(self._sessionmaker, deps, max_jobs=20)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # keep the loop alive (e.g. database briefly unreachable)
                logger.warning("bot_loop_error", error_type=type(exc).__name__)
                ran = 0
            if ran == 0:
                await asyncio.sleep(self._poll)
