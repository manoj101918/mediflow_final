"""Model providers for the patient-record assistant, behind one factory so they can be swapped.

- Embeddings: Voyage AI (`langchain-voyageai`), model and dimension from settings.
- Chat: Groq (`langchain-groq`), model from settings (see `get_chat_model`).
- RAG_FAKE_LLM=true swaps both for deterministic fakes, so tests and E2E need no API keys.

Chunks record which embedding model produced them (`embedding_model_name`), and retrieval only
compares vectors from the same model.
"""

import asyncio
import re
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.embeddings import Embeddings
from langchain_core.embeddings.fake import DeterministicFakeEmbedding
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import SecretStr

from app.core.config import Settings, get_settings

FAKE_EMBEDDING_MODEL = "fake-deterministic"


class ProviderNotConfiguredError(RuntimeError):
    """An API key the configured provider needs is missing."""


def _secret(value: object) -> str | None:
    raw = value.get_secret_value() if hasattr(value, "get_secret_value") else None
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def embedding_model_name(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return FAKE_EMBEDDING_MODEL if settings.rag_fake_llm else settings.embedding_model


class ThrottledEmbeddings(Embeddings):
    """Spaces requests to stay under a provider's requests-per-minute limit.

    Voyage's free tier allows 3 requests a minute; without this, indexing a few records in a
    row is rate-limited. One request per call (a source's chunks are embedded together), and
    chat questions share the same budget.
    """

    def __init__(self, inner: Embeddings, requests_per_minute: int) -> None:
        self._inner = inner
        self._interval = 60.0 / requests_per_minute
        self._next = 0.0
        self._async_lock: asyncio.Lock | None = None
        self._sync_lock = threading.Lock()

    def _reserve(self) -> float:
        """Claim the next request slot; returns how long to wait for it."""
        now = time.monotonic()
        start = max(now, self._next)
        self._next = start + self._interval
        return start - now

    async def _await_turn(self) -> None:
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        async with self._async_lock:
            delay = self._reserve()
        if delay > 0:
            await asyncio.sleep(delay)

    def _sync_turn(self) -> None:
        with self._sync_lock:
            delay = self._reserve()
        if delay > 0:
            time.sleep(delay)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._sync_turn()
        return self._inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        self._sync_turn()
        return self._inner.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        await self._await_turn()
        return await self._inner.aembed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        await self._await_turn()
        return await self._inner.aembed_query(text)


def build_embeddings(settings: Settings) -> Embeddings:
    if settings.rag_fake_llm:
        return DeterministicFakeEmbedding(size=settings.embedding_dim)
    key = _secret(settings.voyage_api_key)
    if key is None:
        raise ProviderNotConfiguredError("VOYAGE_API_KEY is not set")
    # Imported lazily: the Voyage client pulls in heavier dependencies.
    from langchain_voyageai import VoyageAIEmbeddings  # noqa: PLC0415

    voyage = VoyageAIEmbeddings(
        model=settings.embedding_model,
        voyage_api_key=SecretStr(key),
        output_dimension=settings.embedding_dim,
        batch_size=64,
    )
    rpm = settings.embedding_requests_per_minute
    return ThrottledEmbeddings(voyage, rpm) if rpm > 0 else voyage


@lru_cache
def get_embeddings() -> Embeddings:
    """The configured embeddings (cached per process)."""
    return build_embeddings(get_settings())


# --- Chat model ---------------------------------------------------------------------------

# "intent": the booking bot's free-text parser (short JSON, no streaming).
ChatPurpose = Literal["answer", "rewrite", "intent"]

FAKE_CHAT_MODEL = "fake-records-model"
# Short outputs (hidden gpt-oss reasoning counts against the budget too).
_MAX_TOKENS: dict[str, int] = {"rewrite": 200, "intent": 400}


def _reasoning_options(model: str, effort: str) -> dict[str, Any]:
    """Groq reasoning controls differ per model family; reasoning text is never returned."""
    if model.startswith("openai/gpt-oss"):
        return {"reasoning_effort": effort, "model_kwargs": {"include_reasoning": False}}
    if model.startswith("qwen/"):
        return {"reasoning_format": "hidden"}
    return {}


def chat_model_name(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return FAKE_CHAT_MODEL if settings.rag_fake_llm else settings.llm_model


def build_chat_model(settings: Settings, purpose: ChatPurpose = "answer") -> BaseChatModel:
    if settings.rag_fake_llm:
        return FakeRecordsChatModel()
    key = _secret(settings.groq_api_key)
    if key is None:
        raise ProviderNotConfiguredError("GROQ_API_KEY is not set")
    from langchain_groq import ChatGroq  # noqa: PLC0415

    return ChatGroq(
        model=settings.llm_model,
        api_key=SecretStr(key),
        # Short standalone queries for retrieval; full answers otherwise.
        max_tokens=_MAX_TOKENS.get(purpose, settings.llm_max_tokens),
        temperature=0,
        timeout=settings.llm_timeout_seconds,
        max_retries=1,
        streaming=purpose == "answer",
        **_reasoning_options(settings.llm_model, settings.llm_reasoning_effort),
    )


@dataclass(frozen=True)
class RagProviders:
    """Everything the chat service needs from model providers."""

    chat: BaseChatModel
    rewriter: BaseChatModel
    embeddings: Embeddings
    embedding_model: str
    chat_model: str


@lru_cache
def get_rag_providers() -> RagProviders:
    """Configured providers (cached). Raises ProviderNotConfiguredError if a key is missing."""
    settings = get_settings()
    return RagProviders(
        chat=build_chat_model(settings, "answer"),
        rewriter=build_chat_model(settings, "rewrite"),
        embeddings=get_embeddings(),
        embedding_model=embedding_model_name(settings),
        chat_model=chat_model_name(settings),
    )


# --- Deterministic fake (RAG_FAKE_LLM, tests, E2E) --------------------------------------

_SOURCE = re.compile(r'<source id="(\d+)"[^>]*label="([^"]*)"[^>]*>\n(.*?)\n</source>', re.S)
_WORD = re.compile(r"[a-z0-9]{3,}")


def _words(value: str) -> set[str]:
    return set(_WORD.findall(value.lower()))


def fake_answer(prompt: str) -> str:
    """Answer from the best-matching source in the prompt, citing it.

    Reads the <source> blocks of the last message and the doctor's question; never invents
    facts. With no matching record it says so, which is what the real prompt asks for.
    """
    question = prompt.rsplit("Doctor's question:", 1)[-1]
    if "Rewrite" in prompt.split("\n", 1)[0]:
        return question.strip()
    sources = [(int(n), label, body.strip()) for n, label, body in _SOURCE.findall(prompt)]
    wanted = _words(question)
    scored = sorted(
        ((len(wanted & _words(body)), n, label, body) for n, label, body in sources if n != 1),
        reverse=True,
    )
    if not scored or scored[0][0] == 0:
        return "The available records do not contain this information [1]."
    _, n, label, body = scored[0]
    snippet = " ".join(body.split())[:220]
    return f"According to {label} [{n}]: {snippet}"


class FakeRecordsChatModel(BaseChatModel):
    """Streams `fake_answer()` word by word, with token usage, like a real provider."""

    @property
    def _llm_type(self) -> str:
        return "fake-records"

    def _answer(self, messages: list[BaseMessage]) -> str:
        return fake_answer(str(messages[-1].content) if messages else "")

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = self._answer(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        text = self._answer(messages)
        words = text.split(" ")
        for i, word in enumerate(words):
            yield ChatGenerationChunk(
                message=AIMessageChunk(content=word if i == 0 else f" {word}")
            )
        prompt_chars = sum(len(str(m.content)) for m in messages)
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                usage_metadata={
                    "input_tokens": prompt_chars // 4,
                    "output_tokens": len(words),
                    "total_tokens": prompt_chars // 4 + len(words),
                },
            )
        )
