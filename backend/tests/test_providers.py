"""Provider helpers that need no database."""

import asyncio
import time

from langchain_core.embeddings.fake import DeterministicFakeEmbedding

from app.services.rag.providers import ThrottledEmbeddings


async def test_throttled_embeddings_space_requests() -> None:
    throttled = ThrottledEmbeddings(DeterministicFakeEmbedding(size=8), requests_per_minute=600)
    started = time.monotonic()
    # Four concurrent requests at 600/min (one per 0.1 s) take at least 0.3 s in total.
    results = await asyncio.gather(
        throttled.aembed_query("a"),
        throttled.aembed_documents(["b", "c"]),
        throttled.aembed_query("d"),
        throttled.aembed_query("e"),
    )
    elapsed = time.monotonic() - started
    assert elapsed >= 0.29
    assert len(results[1]) == 2 and len(results[0]) == 8
