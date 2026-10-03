"""Live evaluation of the assistant on the seeded test patient (real Groq + Voyage APIs).

    cd backend
    uv run python -m scripts.seed_clinical          # once, with VOYAGE_API_KEY set
    uv run python -m pytest -m live -s tests/live   # prints a scorecard

Skipped unless run with `-m live` and both API keys are configured. Read-only: it answers
questions over the seed clinic without saving chat messages. Paced for the Groq free tier
(8K tokens per minute): it waits between questions and honours rate limits.
"""

import asyncio
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import pytest
from langchain_core.embeddings import Embeddings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.models import Patient
from app.services.booking.timeutil import clinic_tz, today_local
from app.services.rag.chat import build_context
from app.services.rag.citations import cited_numbers, clean_markers
from app.services.rag.providers import (
    ProviderNotConfiguredError,
    RagProviders,
    build_chat_model,
    build_embeddings,
    embedding_model_name,
)

pytestmark = pytest.mark.live

PRAKASH = UUID("2037da99-bae2-d71e-a051-2f8a85bb826f")
# Free tiers: Groq 8K tokens/min, Voyage 3 requests/min (one query embedding per question).
PAUSE_SECONDS = 25
NOT_IN_RECORDS = re.compile(
    r"(don.?t|do not|does not|doesn.?t) (contain|include|mention|have)|not (in|found in|"
    r"available in|recorded in|documented in) the (records|file)|no record|not recorded|"
    r"not documented|no information",
    re.I,
)


@dataclass(frozen=True)
class Case:
    question: str
    # Every group must match; a group matches if any of its alternatives appears.
    facts: tuple[tuple[str, ...], ...] = ()
    unanswerable: bool = False


CASES = (
    Case("What is the HbA1c trend?", (("8.1",), ("7.4",), ("6.9",))),
    Case("What is the patient allergic to?", (("penicillin",),)),
    Case("Which medicines is he currently taking?", (("metformin",), ("telmisartan",))),
    Case("Why was glimepiride stopped?", (("hypoglyc", "low sugar", "low blood sugar"),)),
    Case("When was glimepiride started?", (("12 mar", "mar 12", "2026-03-12", "march 2026"),)),
    Case("What metformin dose was started at the first visit?", (("500",),)),
    Case("What is the current metformin dose?", (("1000",),)),
    Case("What did the latest lipid profile show for LDL?", (("118",),)),
    Case("What was diagnosed for the knee?", (("osteoarthritis",),)),
    Case("Which doctor saw him for knee pain?", (("khan",),)),
    Case("What was the blood pressure at the last visit?", (("130/84",),)),
    Case("How has his weight changed across visits?", (("84",), ("79",))),
    Case(
        "What happened after the metformin dose was increased?",
        (("stomach", "gastro", "gi upset", "upset"),),
    ),
    Case("What was the urine microalbumin result?", (("18",),)),
    Case("When is the next follow-up due?", (("15 dec", "dec 15", "2026-12-15", "december"),)),
    # Structured lab results (Phase 3 backfill of the seed lab reports).
    Case("What was the fasting blood sugar in December 2025?", (("168",),)),
    Case("What was the post-prandial blood sugar on the first lab test?", (("246",),)),
    Case("What is the latest triglyceride level?", (("160",),)),
    Case("Which values were flagged high in the latest lab results?", (("ldl",), ("triglycer",))),
    Case("What was the serum creatinine?", (("0.9",),)),
    Case("What is his HIV status?", unanswerable=True),
    Case("Has he ever had a colonoscopy?", unanswerable=True),
    Case("What was his vitamin B12 level?", unanswerable=True),
)


def _rate_limited(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 429 or type(exc).__name__ == "RateLimitError"


class RetryingEmbeddings(Embeddings):
    """Waits out free-tier rate limits, so the eval measures real hybrid retrieval
    (the app itself falls back to full-text search instead of waiting)."""

    def __init__(self, inner: Embeddings) -> None:
        self._inner = inner

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._inner.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._inner.aembed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        for attempt in range(4):
            try:
                return await self._inner.aembed_query(text)
            except Exception as exc:
                if not _rate_limited(exc) or attempt == 3:
                    raise
                await asyncio.sleep(65)
        raise AssertionError("unreachable")


@pytest.fixture(scope="module")
def providers() -> RagProviders:
    settings = get_settings()
    if settings.rag_fake_llm:
        pytest.skip("RAG_FAKE_LLM is on; the live eval needs the real providers")
    try:
        return RagProviders(
            chat=build_chat_model(settings, "answer"),
            rewriter=build_chat_model(settings, "rewrite"),
            embeddings=RetryingEmbeddings(build_embeddings(settings)),
            embedding_model=embedding_model_name(settings),
            chat_model=settings.llm_model,
        )
    except ProviderNotConfiguredError as exc:
        pytest.skip(str(exc))


async def _answer(
    sessionmaker: async_sessionmaker[AsyncSession], providers: RagProviders, question: str
) -> tuple[str, int]:
    async with sessionmaker() as session:
        patient = await session.get(Patient, PRAKASH)
        if patient is None:
            pytest.skip("seed patient missing: run supabase/seed.sql and scripts.seed_clinical")
        today: date = today_local(clinic_tz())
        context = await build_context(
            session, patient, question, [], providers, get_settings(), today
        )
    for attempt in range(3):
        try:
            reply = await providers.chat.ainvoke(context.messages)
            return clean_markers(reply.text), len(context.sources)
        except Exception as exc:  # rate limited on the free tier: wait and retry
            if not _rate_limited(exc) or attempt == 2:
                raise
            await asyncio.sleep(60)
    raise AssertionError("unreachable")


def _grade(case: Case, answer: str, source_count: int) -> tuple[bool, str]:
    # Models often use non-breaking spaces/hyphens ("12 Mar 2026"); compare plain text.
    lowered = " ".join(unicodedata.normalize("NFKC", answer).split()).lower()
    cited = [n for n in cited_numbers(answer) if 1 <= n <= source_count]
    if case.unanswerable:
        ok = bool(NOT_IN_RECORDS.search(answer))
        return ok, "" if ok else "did not say the records lack this"
    missing = [group[0] for group in case.facts if not any(a in lowered for a in group)]
    problems = []
    if missing:
        problems.append(f"missing {missing}")
    if not cited:
        problems.append("no valid citation")
    return not problems, "; ".join(problems)


async def test_live_eval_scorecard(
    sessionmaker: async_sessionmaker[AsyncSession], providers: RagProviders
) -> None:
    rows: list[tuple[bool, Case, str, str]] = []
    for i, case in enumerate(CASES):
        if i:
            await asyncio.sleep(PAUSE_SECONDS)
        answer, sources = await _answer(sessionmaker, providers, case.question)
        ok, why = _grade(case, answer, sources)
        rows.append((ok, case, why, answer))

    passed = sum(ok for ok, *_ in rows)
    # Answers can contain characters a Windows console code page cannot print.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")
    print(f"\n=== RAG live eval: {passed}/{len(rows)} passed ({get_settings().llm_model}) ===")
    for ok, case, why, answer in rows:
        kind = "N/A " if case.unanswerable else "fact"
        print(f"[{'PASS' if ok else 'FAIL'}] {kind} {case.question}")
        if not ok:
            print(f"        {why}\n        answer: {' '.join(answer.split())[:300]}")
    assert passed == len(rows), f"{len(rows) - passed} eval question(s) failed (see scorecard)"
