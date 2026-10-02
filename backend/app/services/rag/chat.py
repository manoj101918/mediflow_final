"""Patient chat: prepare a turn (access, retrieval, prompt), then stream the answer.

`prepare_turn` does everything that can fail with a normal HTTP error before streaming starts:
access check, session ownership, retrieval, saving the question and the access-log row.
`stream_turn` streams tokens and always ends with either `citations` + `done` or `error`;
the assistant message is saved with token usage and latency either way.

Never log prompts, answers or record text: only ids, sizes and error types.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from uuid import UUID

import structlog
from langchain_core.messages import BaseMessage
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models import (
    ChatRole,
    Patient,
    PatientChatMessage,
    PatientChatSession,
    RecordAccessAction,
)
from app.services.booking.actor import StaffActor
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success
from app.services.rag.citations import citations_for, clean_markers, normalize_markers
from app.services.rag.prompt import MAX_CONTEXT_CHARS, Source, build_messages
from app.services.rag.providers import ProviderNotConfiguredError, RagProviders
from app.services.rag.retriever import ChunkHit, PatientRecordRetriever, sort_by_date
from app.services.rag.rewrite import recency_window, rewrite_question
from app.services.rag.snapshot import patient_summary
from app.services.records.access import chart_patient
from app.services.records.audit import log_access

logger = structlog.get_logger(__name__)

EventName = Literal["token", "citations", "done", "error"]


@dataclass(frozen=True)
class ChatEvent:
    event: EventName
    data: dict[str, Any]


@dataclass(frozen=True)
class PreparedTurn:
    session_id: UUID
    clinic_id: UUID
    question_id: UUID
    messages: list[BaseMessage]
    sources: list[Source]


async def _chat_session(
    session: AsyncSession,
    actor: StaffActor,
    patient_id: UUID,
    session_id: UUID | None,
    question: str,
) -> PatientChatSession | None:
    if session_id is not None:
        # A conversation belongs to the doctor who started it.
        return await session.scalar(
            select(PatientChatSession).where(
                PatientChatSession.id == session_id,
                PatientChatSession.patient_id == patient_id,
                PatientChatSession.user_id == actor.user_id,
            )
        )
    title = " ".join(question.split())
    chat = PatientChatSession(
        clinic_id=actor.clinic_id,
        patient_id=patient_id,
        user_id=actor.user_id,
        doctor_id=actor.doctor_id,
        title=title[:80] + ("…" if len(title) > 80 else ""),
    )
    session.add(chat)
    await session.flush()
    return chat


async def _history(session: AsyncSession, session_id: UUID, turns: int) -> list[tuple[str, str]]:
    """The last `turns` question/answer pairs, oldest first (failed answers skipped)."""
    if turns <= 0:
        return []
    rows = await session.execute(
        select(PatientChatMessage.role, PatientChatMessage.content)
        .where(
            PatientChatMessage.session_id == session_id,
            PatientChatMessage.error_code.is_(None),
        )
        .order_by(PatientChatMessage.created_at.desc())
        .limit(turns * 2)
    )
    return [(role.value, content) for role, content in reversed(list(rows))]


def _source(n: int, hit: ChunkHit) -> Source:
    label = str(hit.metadata.get("label") or hit.source_type.title())
    extra: dict[str, Any] = {}
    if hit.source_type == "lab_result":
        # One chunk per released test of an order: cite the order and that test.
        label = f"Lab {hit.metadata.get('test_code', '')} {hit.metadata.get('order_number', '')}"
        extra["item_id"] = hit.metadata.get("order_item_id")
    page = hit.metadata.get("page")
    return Source(
        n=n,
        source_type=hit.source_type,
        source_id=hit.source_id,
        label=" ".join(label.split()),
        source_date=hit.source_date,
        content=hit.content,
        page=int(page) if isinstance(page, int) else None,
        extra=extra,
    )


def _select_context(ranked: list[ChunkHit], budget: int) -> list[ChunkHit]:
    """Keep the most important chunks that fit the budget, then order them by date."""
    kept: list[ChunkHit] = []
    used = 0
    seen: set[UUID] = set()
    for hit in ranked:
        if hit.id in seen:
            continue
        seen.add(hit.id)
        if used + len(hit.content) > budget and kept:
            continue
        kept.append(hit)
        used += len(hit.content)
    return sort_by_date(kept)


async def prepare_turn(
    session: AsyncSession,
    actor: StaffActor,
    patient_id: UUID,
    session_id: UUID | None,
    question: str,
    providers: RagProviders,
    settings: Settings,
    today: date,
) -> BookingResult[PreparedTurn]:
    allowed = await chart_patient(session, actor, patient_id)
    if not allowed.ok:
        return failure(allowed.code or BookingErrorCode.FORBIDDEN, allowed.message)
    patient = allowed.unwrap()
    question = question.strip()
    if not question:
        return failure(BookingErrorCode.VALIDATION, "Ask a question.")

    chat = await _chat_session(session, actor, patient_id, session_id, question)
    if chat is None:
        await session.rollback()
        return failure(BookingErrorCode.NOT_FOUND, "Conversation not found.")
    history = await _history(session, chat.id, settings.rag_max_history_turns)
    context = await build_context(session, patient, question, history, providers, settings, today)

    asked = PatientChatMessage(
        clinic_id=actor.clinic_id, session_id=chat.id, role=ChatRole.USER, content=question
    )
    session.add(asked)
    log_access(session, actor, patient.id, RecordAccessAction.CHAT_QUESTION, session_id=chat.id)
    await session.flush()
    prepared = PreparedTurn(chat.id, actor.clinic_id, asked.id, context.messages, context.sources)
    await session.commit()
    logger.info(
        "chat_prepared",
        session_id=str(chat.id),
        sources=len(context.sources),
        rewritten=context.rewritten,
        recency=context.recency,
    )
    return success(prepared)


@dataclass(frozen=True)
class TurnContext:
    messages: list[BaseMessage]
    sources: list[Source]
    rewritten: bool
    recency: int | None


async def build_context(
    session: AsyncSession,
    patient: Patient,
    question: str,
    history: list[tuple[str, str]],
    providers: RagProviders,
    settings: Settings,
    today: date,
) -> TurnContext:
    """Retrieval + prompt for one question (no writes). Access must already be checked."""
    # Standalone query for follow-ups, hybrid search, recent visits for time questions.
    query = await rewrite_question(providers.rewriter, history, question)
    retriever = PatientRecordRetriever(
        session=session,
        embeddings=providers.embeddings,
        clinic_id=patient.clinic_id,
        patient_id=patient.id,
        embedding_model=providers.embedding_model,
        top_k=settings.rag_top_k,
    )
    ranked = await retriever.search(query)
    window = recency_window(question)
    if window is not None:
        ranked += await retriever.recent("consultation", window)
        ranked += await retriever.recent("lab_result", window)
    summary = await patient_summary(session, patient, today)
    context = _select_context(ranked, MAX_CONTEXT_CHARS - len(summary))

    sources = [Source(1, "summary", patient.id, "Patient summary", today, summary)]
    sources += [_source(i, hit) for i, hit in enumerate(context, start=2)]
    return TurnContext(
        build_messages(sources, history, question), sources, query != question, window
    )


def _friendly_error(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, TimeoutError):
        return "TIMEOUT", "The assistant took too long to answer. Please try again."
    if getattr(exc, "status_code", None) == 429 or type(exc).__name__ == "RateLimitError":
        return "RATE_LIMITED", "The AI service is busy right now. Try again in a minute."
    if isinstance(exc, ProviderNotConfiguredError):
        return "NOT_CONFIGURED", "The assistant is not configured on this server."
    return "PROVIDER_ERROR", "The assistant is unavailable right now. Please try again."


async def stream_turn(
    sessionmaker: async_sessionmaker[AsyncSession],
    prepared: PreparedTurn,
    providers: RagProviders,
    settings: Settings,
) -> AsyncIterator[ChatEvent]:
    started = time.monotonic()
    parts: list[str] = []
    usage: dict[str, Any] = {}
    error: tuple[str, str] | None = None
    try:
        async with asyncio.timeout(settings.llm_timeout_seconds * 2):
            async for chunk in providers.chat.astream(prepared.messages):
                piece = normalize_markers(chunk.text)
                if piece:
                    parts.append(piece)
                    yield ChatEvent("token", {"text": piece})
                if chunk.usage_metadata:
                    usage = dict(chunk.usage_metadata)
    except Exception as exc:
        error = _friendly_error(exc)
        logger.warning(
            "chat_failed", session_id=str(prepared.session_id), error_type=type(exc).__name__
        )

    answer = clean_markers("".join(parts)).strip()
    citations = [] if error else citations_for(answer, prepared.sources)
    async with sessionmaker() as session:
        message = PatientChatMessage(
            clinic_id=prepared.clinic_id,
            session_id=prepared.session_id,
            role=ChatRole.ASSISTANT,
            content=answer if not error else (answer or error[1]),
            citations=citations,
            model=providers.chat_model,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            latency_ms=int((time.monotonic() - started) * 1000),
            error_code=error[0] if error else None,
        )
        session.add(message)
        await session.execute(
            text("update public.patient_chat_sessions set updated_at = now() where id = :id"),
            {"id": prepared.session_id},
        )
        await session.commit()
        ids = {"session_id": str(prepared.session_id), "message_id": str(message.id)}

    if error:
        yield ChatEvent("error", {"code": error[0], "message": error[1], **ids})
        return
    yield ChatEvent("citations", {"citations": citations})
    yield ChatEvent("done", ids)
    logger.info(
        "chat_answered",
        session_id=str(prepared.session_id),
        output_tokens=usage.get("output_tokens"),
        citations=len(citations),
        latency_ms=message.latency_ms,
    )
