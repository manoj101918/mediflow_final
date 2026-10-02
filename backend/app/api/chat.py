"""Patient-record assistant: streamed answers (Server-Sent Events) and conversation history.

POST /patients/{id}/chat streams `text/event-stream`:
  event: token      data: {"text": "..."}             (many)
  event: citations  data: {"citations": [...]}        (then)
  event: done       data: {"session_id", "message_id"}
  event: error      data: {"code", "message", "session_id", "message_id"}  (instead of both)
Errors found before streaming (access, rate limit, unknown conversation) are normal JSON errors.
"""

import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.results import unwrap
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.rate_limit import allow_chat
from app.db.models import PatientChatMessage, PatientChatSession
from app.deps import AuthUser, DbSession, SessionFactory, clinic_today, staff_actor
from app.schemas.chat import ChatIn, ChatMessageOut, ChatSessionOut
from app.services.rag.chat import ChatEvent, prepare_turn, stream_turn
from app.services.rag.providers import (
    ProviderNotConfiguredError,
    RagProviders,
    get_rag_providers,
)
from app.services.records.access import chart_patient, clinician_check

router = APIRouter(tags=["chat"])


def rag_providers() -> RagProviders:
    try:
        return get_rag_providers()
    except ProviderNotConfiguredError as exc:
        raise AppError(
            503, "ASSISTANT_UNAVAILABLE", "The assistant is not configured on this server."
        ) from exc


Providers = Annotated[RagProviders, Depends(rag_providers)]


def _sse(event: ChatEvent) -> str:
    return f"event: {event.event}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"


@router.post("/patients/{patient_id}/chat")
async def chat(
    patient_id: UUID,
    body: ChatIn,
    session: DbSession,
    factory: SessionFactory,
    user: AuthUser,
    providers: Providers,
) -> StreamingResponse:
    actor = staff_actor(user)
    unwrap(clinician_check(actor))
    if not allow_chat(user.id):
        raise AppError(
            429, "RATE_LIMITED", "Too many questions in a short time. Wait a moment and retry."
        )
    settings = get_settings()
    prepared = unwrap(
        await prepare_turn(
            session,
            actor,
            patient_id,
            body.session_id,
            body.message,
            providers,
            settings,
            clinic_today(user),
        )
    )

    async def events() -> AsyncIterator[str]:
        async for event in stream_turn(factory, prepared, providers, settings):
            yield _sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/patients/{patient_id}/chat/sessions")
async def list_sessions(
    patient_id: UUID, session: DbSession, user: AuthUser
) -> list[ChatSessionOut]:
    """The signed-in doctor's conversations about this patient, newest first."""
    actor = staff_actor(user)
    unwrap(await chart_patient(session, actor, patient_id))
    rows = await session.scalars(
        select(PatientChatSession)
        .where(
            PatientChatSession.patient_id == patient_id,
            PatientChatSession.user_id == user.id,
        )
        .order_by(PatientChatSession.updated_at.desc())
        .limit(50)
    )
    return [
        ChatSessionOut(id=s.id, title=s.title, created_at=s.created_at, updated_at=s.updated_at)
        for s in rows
    ]


@router.get("/chat/sessions/{session_id}/messages")
async def list_messages(
    session_id: UUID, session: DbSession, user: AuthUser
) -> list[ChatMessageOut]:
    unwrap(clinician_check(staff_actor(user)))
    owned = await session.scalar(
        select(PatientChatSession.id).where(
            PatientChatSession.id == session_id,
            PatientChatSession.user_id == user.id,
            PatientChatSession.clinic_id == user.clinic_id,
        )
    )
    if owned is None:
        raise AppError(404, "NOT_FOUND", "Conversation not found.")
    rows = await session.scalars(
        select(PatientChatMessage)
        .where(PatientChatMessage.session_id == session_id)
        .order_by(PatientChatMessage.created_at)
    )
    return [
        ChatMessageOut(
            id=m.id,
            role=m.role.value,
            content=m.content,
            citations=ChatMessageOut.citations_from(m.citations),
            error_code=m.error_code,
            created_at=m.created_at,
        )
        for m in rows
    ]
