"""Patient chat over Server-Sent Events (fake chat model, fake embeddings)."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from sqlalchemy import text

from app.core.config import get_settings
from app.services.rag.providers import RagProviders
from tests.conftest import ClinicFixture, Ingestion, auth, parse_sse
from tests.records_utils import Chart


async def ready_patient(client: AsyncClient, clinic: ClinicFixture, ingestion: Ingestion) -> Chart:
    s = await Chart(clinic).build()
    await client.put(
        f"/api/patients/{s.ravi}/medical-profile",
        json={"allergies": ["Penicillin"], "chronic_conditions": ["Type 2 diabetes"]},
        headers=auth(s.doc_a.user_id),
    )
    await s.write(client, s.visit, s.doc_a.user_id)
    await s.complete(client, s.visit, s.doc_a.user_id)
    await ingestion.run()
    return s


async def ask(
    client: AsyncClient, s: Chart, message: str, user: uuid.UUID | None = None, **extra: Any
) -> Any:
    return await client.post(
        f"/api/patients/{s.ravi}/chat",
        json={"message": message, **extra},
        headers=auth(user or s.doc_a.user_id),
    )


async def test_stream_order_citations_and_persistence(
    client: AsyncClient, clinic: ClinicFixture, ingestion: Ingestion, rag: RagProviders
) -> None:
    s = await ready_patient(client, clinic, ingestion)
    response = await ask(client, s, "What dose of Metformin was prescribed?")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[-2:] == ["citations", "done"]
    assert set(names[:-2]) == {"token"} and len(names) > 3

    answer = "".join(data["text"] for name, data in events if name == "token")
    assert "[" in answer and "Metformin" in answer
    citations = events[-2][1]["citations"]
    assert citations, answer
    consultation_id = await s_scalar(
        clinic, "select id from consultations where appointment_id = :a", a=s.visit
    )
    assert any(
        c["source_type"] == "consultation" and c["source_id"] == str(consultation_id)
        for c in citations
    )
    assert all(c["label"] for c in citations)

    done = events[-1][1]
    history = await client.get(
        f"/api/chat/sessions/{done['session_id']}/messages", headers=auth(s.doc_a.user_id)
    )
    messages = history.json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["id"] == done["message_id"]
    assert messages[1]["content"] == answer.strip()
    assert messages[1]["citations"] == citations
    async with clinic.sessionmaker() as session:
        row = (
            await session.execute(
                text(
                    "select model, input_tokens, output_tokens, latency_ms from "
                    "patient_chat_messages where id = :m"
                ),
                {"m": done["message_id"]},
            )
        ).one()
    assert row[0] == "pytest-fake-chat" and row[1] > 0 and row[2] > 0 and row[3] >= 0

    sessions = await client.get(
        f"/api/patients/{s.ravi}/chat/sessions", headers=auth(s.doc_a.user_id)
    )
    assert [x["id"] for x in sessions.json()] == [done["session_id"]]
    logged = await s_scalar(
        clinic,
        "select count(*) from patient_record_access_log where action = 'chat_question' "
        "and session_id = :s",
        s=done["session_id"],
    )
    assert logged == 1


async def test_follow_up_continues_the_session(
    client: AsyncClient, clinic: ClinicFixture, ingestion: Ingestion, rag: RagProviders
) -> None:
    s = await ready_patient(client, clinic, ingestion)
    first = parse_sse((await ask(client, s, "What was the diagnosis?")).text)
    session_id = first[-1][1]["session_id"]
    second = parse_sse(
        (await ask(client, s, "And the Metformin dose?", session_id=session_id)).text
    )
    assert second[-1] == (
        "done",
        {"session_id": session_id, "message_id": second[-1][1]["message_id"]},
    )
    count = await s_scalar(
        clinic, "select count(*) from patient_chat_messages where session_id = :s", s=session_id
    )
    assert count == 4


async def test_answers_only_from_records(
    client: AsyncClient, clinic: ClinicFixture, ingestion: Ingestion, rag: RagProviders
) -> None:
    s = await ready_patient(client, clinic, ingestion)
    events = parse_sse((await ask(client, s, "Zebra xylophone quantum?")).text)
    answer = "".join(d["text"] for n, d in events if n == "token")
    assert "do not contain" in answer
    assert [c["n"] for c in events[-2][1]["citations"]] == [1]  # the patient summary


async def test_access_rules(
    client: AsyncClient, clinic: ClinicFixture, ingestion: Ingestion, rag: RagProviders
) -> None:
    s = await ready_patient(client, clinic, ingestion)
    assert (await ask(client, s, "Diagnosis?", user=s.desk.user_id)).status_code == 403
    assert (await ask(client, s, "Diagnosis?", user=s.admin.user_id)).status_code == 403
    sessions = await client.get(
        f"/api/patients/{s.ravi}/chat/sessions", headers=auth(s.desk.user_id)
    )
    assert sessions.status_code == 403
    unknown = await ask(client, s, "Diagnosis?", session_id=str(uuid.uuid4()))
    assert unknown.status_code == 404

    # A conversation belongs to the doctor who started it.
    mine = parse_sse((await ask(client, s, "Diagnosis?")).text)[-1][1]["session_id"]
    other = await ask(client, s, "Diagnosis?", user=s.doc_b.user_id, session_id=mine)
    assert other.status_code == 404
    other_read = await client.get(
        f"/api/chat/sessions/{mine}/messages", headers=auth(s.doc_b.user_id)
    )
    assert other_read.status_code == 404
    # But any doctor may start their own conversation about the patient.
    assert (await ask(client, s, "Diagnosis?", user=s.doc_c.user_id)).status_code == 200


async def test_rate_limit_per_user(
    client: AsyncClient,
    clinic: ClinicFixture,
    ingestion: Ingestion,
    rag: RagProviders,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = await ready_patient(client, clinic, ingestion)
    monkeypatch.setattr(get_settings(), "chat_rate_limit", "2/minute")
    assert (await ask(client, s, "One?")).status_code == 200
    assert (await ask(client, s, "Two?")).status_code == 200
    limited = await ask(client, s, "Three?")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    # Another doctor has their own allowance.
    assert (await ask(client, s, "One?", user=s.doc_c.user_id)).status_code == 200


class ProviderBusyError(Exception):
    status_code = 429


class FailingChatModel(BaseChatModel):
    """Streams a couple of tokens, then the provider says 429."""

    @property
    def _llm_type(self) -> str:
        return "failing"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise ProviderBusyError

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        from langchain_core.messages import AIMessageChunk  # noqa: PLC0415

        yield ChatGenerationChunk(message=AIMessageChunk(content="Partial"))
        raise ProviderBusyError


async def test_provider_error_becomes_error_event(
    client: AsyncClient,
    clinic: ClinicFixture,
    ingestion: Ingestion,
    rag: RagProviders,
    app: Any,
) -> None:
    s = await ready_patient(client, clinic, ingestion)
    from app.api.chat import rag_providers  # noqa: PLC0415

    failing = RagProviders(
        chat=FailingChatModel(),
        rewriter=rag.rewriter,
        embeddings=rag.embeddings,
        embedding_model=rag.embedding_model,
        chat_model=rag.chat_model,
    )
    app.dependency_overrides[rag_providers] = lambda: failing
    events = parse_sse((await ask(client, s, "Diagnosis?")).text)
    assert [n for n, _ in events] == ["token", "error"]
    error = events[-1][1]
    assert error["code"] == "RATE_LIMITED"
    assert "busy" in error["message"]
    code = await s_scalar(
        clinic, "select error_code from patient_chat_messages where id = :m", m=error["message_id"]
    )
    assert code == "RATE_LIMITED"


async def s_scalar(clinic: ClinicFixture, sql: str, **params: Any) -> Any:
    async with clinic.sessionmaker() as session:
        return await session.scalar(text(sql), params)
