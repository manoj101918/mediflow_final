"""Patient chat schemas. Mirror in frontend/src/types/api.ts."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, StringConstraints

from app.schemas.common import UtcDateTime


class ChatIn(BaseModel):
    session_id: UUID | None = None
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class Citation(BaseModel):
    """What an [n] marker in an answer points at."""

    n: int
    source_type: Literal["summary", "profile", "consultation", "report"]
    source_id: UUID
    label: str
    date: str | None
    page: int | None


class ChatSessionOut(BaseModel):
    id: UUID
    title: str
    created_at: UtcDateTime
    updated_at: UtcDateTime


class ChatMessageOut(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation]
    error_code: str | None
    created_at: UtcDateTime

    @classmethod
    def citations_from(cls, raw: list[dict[str, Any]]) -> list[Citation]:
        return [Citation.model_validate(c) for c in raw]
