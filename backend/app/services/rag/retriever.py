"""Patient-scoped hybrid retrieval over patient_record_chunks.

The retriever is constructed for ONE (clinic, patient) and every SQL statement filters on both
(and on the embedding model), so another patient's chunks can never be returned.

- Vector arm: exact cosine distance over this patient's chunks only (a materialized CTE).
  A patient has few chunks, so this is fast, and unlike HNSW-then-filter it never loses
  results to the filter.
- Full-text arm: the question's terms OR-ed together (plainto_tsquery), ranked by ts_rank_cd.
  Catches drug and lab-test names that embeddings blur.
- The two rankings are merged with reciprocal rank fusion (k = 60).
"""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

import structlog
from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import vector_literal

logger = structlog.get_logger(__name__)

RRF_K = 60

_SCOPE = "clinic_id = :clinic_id and patient_id = :patient_id and embedding_model = :model"

_VECTOR = text(
    f"""
    with mine as materialized (
      select id, embedding from public.patient_record_chunks where {_SCOPE}
    )
    select id from mine
    order by embedding operator(extensions.<=>) cast(cast(:query as text) as extensions.vector)
    limit :limit
    """  # noqa: S608 - static SQL, values are bound parameters
)

_FULL_TEXT = text(
    """
    with q as (
      select cast(replace(plainto_tsquery('english', :query)::text, '&', '|') as tsquery) as tsq
    )
    select c.id
    from public.patient_record_chunks c, q
    where c.clinic_id = :clinic_id and c.patient_id = :patient_id
      and c.embedding_model = :model
      and q.tsq::text <> '' and c.content_tsv @@ q.tsq
    order by ts_rank_cd(c.content_tsv, q.tsq) desc
    limit :limit
    """
)

_ROWS = text(
    f"""
    select id, source_type::text, source_id, source_date, chunk_index, content, metadata
    from public.patient_record_chunks
    where {_SCOPE} and id = any(:ids)
    """  # noqa: S608 - static SQL, values are bound parameters
)

_RECENT = text(
    f"""
    select id from public.patient_record_chunks
    where {_SCOPE} and source_type = cast(:source_type as public.record_source_type)
      and source_id in (
        select source_id from public.patient_record_chunks
        where {_SCOPE} and source_type = cast(:source_type as public.record_source_type)
        group by source_id
        order by max(source_date) desc nulls last
        limit :sources
      )
    """  # noqa: S608 - static SQL, values are bound parameters
)


def reciprocal_rank_fusion(rankings: list[list[UUID]], k: int = RRF_K) -> list[UUID]:
    scores: dict[UUID, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda cid: scores[cid], reverse=True)


@dataclass(frozen=True)
class ChunkHit:
    id: UUID
    source_type: str
    source_id: UUID
    source_date: date | None
    chunk_index: int
    content: str
    metadata: dict[str, Any]

    def document(self) -> Document:
        return Document(
            page_content=self.content,
            id=str(self.id),
            metadata={
                **self.metadata,
                "chunk_id": str(self.id),
                "source_type": self.source_type,
                "source_id": str(self.source_id),
                "source_date": self.source_date.isoformat() if self.source_date else None,
                "chunk_index": self.chunk_index,
            },
        )


def sort_by_date(hits: list[ChunkHit]) -> list[ChunkHit]:
    """Oldest first (undated last), so the model reads the record as a timeline."""
    return sorted(
        hits,
        key=lambda h: (
            h.source_date is None,
            h.source_date or date.min,
            str(h.source_id),
            h.chunk_index,
        ),
    )


class PatientRecordRetriever(BaseRetriever):
    """LangChain retriever bound to one patient. Async only (the app is async)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session: AsyncSession
    embeddings: Embeddings
    clinic_id: UUID
    patient_id: UUID
    embedding_model: str
    top_k: int = 6

    def _params(self, **extra: Any) -> dict[str, Any]:
        return {
            "clinic_id": self.clinic_id,
            "patient_id": self.patient_id,
            "model": self.embedding_model,
            **extra,
        }

    async def _ids(self, stmt: Any, **extra: Any) -> list[UUID]:
        return [row[0] for row in await self.session.execute(stmt, self._params(**extra))]

    async def fetch(self, ids: list[UUID]) -> list[ChunkHit]:
        if not ids:
            return []
        rows = await self.session.execute(_ROWS, self._params(ids=ids))
        by_id = {
            row[0]: ChunkHit(row[0], row[1], row[2], row[3], row[4], row[5], dict(row[6]))
            for row in rows
        }
        return [by_id[i] for i in ids if i in by_id]

    async def search(self, query: str) -> list[ChunkHit]:
        """Hybrid search; best first.

        If the embedding provider fails (e.g. rate-limited on a free tier), the answer still
        gets full-text results instead of the whole question failing.
        """
        pool = self.top_k * 3
        try:
            vector = vector_literal(await self.embeddings.aembed_query(query))
        except Exception as exc:
            logger.warning("vector_search_skipped", error_type=type(exc).__name__)
            semantic: list[UUID] = []
        else:
            semantic = await self._ids(_VECTOR, query=vector, limit=pool)
        lexical = await self._ids(_FULL_TEXT, query=query, limit=pool)
        fused = reciprocal_rank_fusion([semantic, lexical])[: self.top_k]
        return await self.fetch(fused)

    async def recent(self, source_type: str, sources: int) -> list[ChunkHit]:
        """Every chunk of the `sources` most recent sources of a type (e.g. last 3 visits)."""
        ids = await self._ids(_RECENT, source_type=source_type, sources=sources)
        return await self.fetch(ids)

    async def _aget_relevant_documents(
        self, query: str, *, run_manager: AsyncCallbackManagerForRetrieverRun
    ) -> list[Document]:
        return [hit.document() for hit in sort_by_date(await self.search(query))]

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        raise NotImplementedError("PatientRecordRetriever is async-only; use ainvoke().")
