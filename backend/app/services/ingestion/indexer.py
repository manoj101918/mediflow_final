"""Write a source's chunks + embeddings to patient_record_chunks.

- Unchanged content (same content hashes for this embedding model) is a no-op.
- Only new/changed chunks are embedded; unchanged ones reuse their stored vectors.
- The source's old chunks are replaced in one transaction (delete, then insert).
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from langchain_core.embeddings import Embeddings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RecordSourceType, vector_literal
from app.services.ingestion.chunking import Chunk


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IndexResult:
    chunks: int
    embedded: int
    unchanged: bool


_EXISTING = text(
    """
    select chunk_index, content_hash, embedding::text
    from public.patient_record_chunks
    where source_type = cast(:source_type as public.record_source_type)
      and source_id = :source_id and embedding_model = :model
    order by chunk_index
    """
)

_DELETE_MODEL = text(
    """
    delete from public.patient_record_chunks
    where source_type = cast(:source_type as public.record_source_type)
      and source_id = :source_id and embedding_model = :model
    """
)

_DELETE_ALL = text(
    """
    delete from public.patient_record_chunks
    where source_type = cast(:source_type as public.record_source_type) and source_id = :source_id
    """
)

_INSERT = text(
    """
    insert into public.patient_record_chunks (
      clinic_id, patient_id, source_type, source_id, source_date, chunk_index, content,
      metadata, embedding, content_hash, embedding_model
    ) values (
      :clinic_id, :patient_id, cast(:source_type as public.record_source_type), :source_id,
      :source_date, :chunk_index, :content, cast(:metadata as jsonb),
      cast(cast(:embedding as text) as extensions.vector), :content_hash, :model
    )
    """
)


async def remove_source(
    session: AsyncSession, source_type: RecordSourceType, source_id: UUID
) -> None:
    """Drop every chunk of a source (all models), e.g. when it no longer has content."""
    await session.execute(_DELETE_ALL, {"source_type": source_type.value, "source_id": source_id})
    await session.commit()


async def index_source(
    session: AsyncSession,
    embeddings: Embeddings,
    model: str,
    *,
    clinic_id: UUID,
    patient_id: UUID,
    source_type: RecordSourceType,
    source_id: UUID,
    source_date: date | None,
    chunks: list[Chunk],
) -> IndexResult:
    if not chunks:
        await remove_source(session, source_type, source_id)
        return IndexResult(chunks=0, embedded=0, unchanged=False)

    key = {"source_type": source_type.value, "source_id": source_id, "model": model}
    existing = list(await session.execute(_EXISTING, key))
    # Release the read transaction before the (slow) embedding call.
    await session.rollback()

    hashes = [content_hash(c.content) for c in chunks]
    if [row[1] for row in existing] == hashes:
        return IndexResult(chunks=len(chunks), embedded=0, unchanged=True)

    stored = {row[1]: str(row[2]) for row in existing}
    missing = [i for i, h in enumerate(hashes) if h not in stored]
    vectors: dict[int, str] = {}
    if missing:
        embedded = await embeddings.aembed_documents([chunks[i].content for i in missing])
        for i, vector in zip(missing, embedded, strict=True):
            vectors[i] = vector_literal(vector)

    await session.execute(_DELETE_MODEL, key)
    for index, (chunk, digest) in enumerate(zip(chunks, hashes, strict=True)):
        await session.execute(
            _INSERT,
            {
                **key,
                "clinic_id": clinic_id,
                "patient_id": patient_id,
                "source_date": source_date,
                "chunk_index": index,
                "content": chunk.content,
                "metadata": json.dumps(chunk.metadata),
                "embedding": vectors.get(index) or stored[digest],
                "content_hash": digest,
            },
        )
    await session.commit()
    return IndexResult(chunks=len(chunks), embedded=len(missing), unchanged=False)
