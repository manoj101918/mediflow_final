"""Ingestion: jobs -> rendered text -> chunks + embeddings (fake provider)."""

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text

from app.core.config import get_settings
from app.db.models import RecordSourceType
from app.services.ingestion import jobs
from app.services.ingestion.worker import IngestionWorker
from tests.conftest import (
    TEST_EMBEDDING_MODEL,
    ClinicFixture,
    FakeReportStorage,
    Ingestion,
    SpyEmbeddings,
    auth,
)
from tests.pdf_utils import PNG_BYTES, make_blank_pdf, make_pdf
from tests.records_utils import Chart

LAB_PDF = make_pdf(
    [
        "Diagnostic lab - HbA1c (glycated haemoglobin)\nResult: 7.4 %  Reference: < 5.7 %",
        "Lipid profile\nLDL cholesterol 118 mg/dL\nComment: repeat in 3 months",
    ]
)


async def chunks_for(clinic: ClinicFixture, source_id: Any) -> list[dict[str, Any]]:
    async with clinic.sessionmaker() as session:
        rows = await session.execute(
            text(
                "select id, chunk_index, content, metadata, embedding_model, source_type::text, "
                "patient_id, source_date from patient_record_chunks where source_id = :s "
                "order by chunk_index"
            ),
            {"s": source_id},
        )
        return [dict(r._mapping) for r in rows]


async def job_statuses(clinic: ClinicFixture, source_id: Any) -> list[str]:
    async with clinic.sessionmaker() as session:
        rows = await session.scalars(
            text(
                "select status::text from ingestion_jobs where source_id = :s order by created_at"
            ),
            {"s": source_id},
        )
        return list(rows)


async def finalized_visit(client: AsyncClient, s: Chart) -> str:
    await s.write(client, s.visit, s.doc_a.user_id)
    done = await s.complete(client, s.visit, s.doc_a.user_id)
    return str(done.json()["consultation_id"])


async def upload(client: AsyncClient, s: Chart, data: bytes, title: str = "HbA1c") -> Response:
    return await client.post(
        f"/api/patients/{s.ravi}/reports",
        data={"title": title, "report_type": "lab", "report_date": "2026-03-12"},
        files={"file": ("r.pdf", data, "application/pdf")},
        headers=auth(s.desk.user_id),
    )


async def test_finalizing_creates_job_and_job_creates_chunks(
    client: AsyncClient, clinic: ClinicFixture, ingestion: Ingestion, spy_embeddings: SpyEmbeddings
) -> None:
    s = await Chart(clinic).build()
    consultation_id = await finalized_visit(client, s)
    assert await job_statuses(clinic, consultation_id) == ["pending"]

    assert await ingestion.run() == 1
    assert await job_statuses(clinic, consultation_id) == ["done"]
    (chunk,) = await chunks_for(clinic, consultation_id)
    assert chunk["source_type"] == "consultation"
    assert chunk["embedding_model"] == TEST_EMBEDDING_MODEL
    assert chunk["patient_id"] == s.ravi
    content = chunk["content"]
    assert content.startswith("Visit on 5 Jan 2026 (IST) with Dr. Test, General.")
    for fact in (
        "Type 2 diabetes mellitus",
        "BP 140/90 mmHg",
        "weight 78.5 kg",
        "1) Metformin 500 mg tablet 1-0-1 after food for 30 days",
    ):
        assert fact in content
    assert chunk["metadata"]["doctor_name"]
    assert len(spy_embeddings.embedded) == 1


async def test_rerun_is_idempotent(
    client: AsyncClient, clinic: ClinicFixture, ingestion: Ingestion, spy_embeddings: SpyEmbeddings
) -> None:
    s = await Chart(clinic).build()
    consultation_id = await finalized_visit(client, s)
    await ingestion.run()
    before = await chunks_for(clinic, consultation_id)

    async with clinic.sessionmaker() as session:
        await jobs.enqueue(
            session,
            clinic.id,
            s.ravi,
            RecordSourceType.CONSULTATION,
            uuid.UUID(consultation_id),
        )
        await session.commit()
    assert await ingestion.run() == 1
    after = await chunks_for(clinic, consultation_id)
    assert [c["id"] for c in after] == [c["id"] for c in before]
    assert len(spy_embeddings.embedded) == 1  # nothing re-embedded


async def test_changed_content_replaces_chunks(
    client: AsyncClient, clinic: ClinicFixture, ingestion: Ingestion, spy_embeddings: SpyEmbeddings
) -> None:
    s = await Chart(clinic).build()
    consultation_id = await finalized_visit(client, s)
    await ingestion.run()
    added = await client.post(
        f"/api/consultations/{consultation_id}/addenda",
        json={"text": "Metformin increased to 1000 mg after review."},
        headers=auth(s.doc_a.user_id),
    )
    assert added.status_code == 201
    await ingestion.run()
    (chunk,) = await chunks_for(clinic, consultation_id)
    assert "Addendum on" in chunk["content"]
    assert "Metformin increased to 1000 mg" in chunk["content"]
    assert len(spy_embeddings.embedded) == 2


async def test_long_visit_is_split_with_heading(
    client: AsyncClient,
    clinic: ClinicFixture,
    ingestion: Ingestion,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "rag_chunk_size", 300)
    s = await Chart(clinic).build()
    await s.write(
        client, s.visit, s.doc_a.user_id, history="Long history. " * 60, diagnosis="Asthma"
    )
    done = await s.complete(client, s.visit, s.doc_a.user_id)
    await ingestion.run()
    chunks = await chunks_for(clinic, done.json()["consultation_id"])
    assert len(chunks) > 1
    assert all(c["content"].startswith("Visit on") for c in chunks)
    assert "(continued)" in chunks[1]["content"]


async def test_profile_is_its_own_chunk(
    client: AsyncClient, clinic: ClinicFixture, ingestion: Ingestion
) -> None:
    s = await Chart(clinic).build()
    await client.put(
        f"/api/patients/{s.ravi}/medical-profile",
        json={"blood_group": "O+", "allergies": ["Penicillin"], "chronic_conditions": ["Asthma"]},
        headers=auth(s.doc_a.user_id),
    )
    await ingestion.run()
    (chunk,) = await chunks_for(clinic, s.ravi)
    assert chunk["source_type"] == "profile"
    assert "Allergies: Penicillin" in chunk["content"]
    assert "Blood group: O+" in chunk["content"]


async def test_pdf_report_is_extracted_per_page(
    client: AsyncClient,
    clinic: ClinicFixture,
    ingestion: Ingestion,
    report_storage: FakeReportStorage,
) -> None:
    s = await Chart(clinic).build()
    report_id = (await upload(client, s, LAB_PDF)).json()["id"]
    await ingestion.run()

    report = (await client.get(f"/api/reports/{report_id}", headers=auth(s.desk.user_id))).json()
    assert report["ingestion_status"] == "indexed"
    assert report["page_count"] == 2
    chunks = await chunks_for(clinic, report_id)
    assert [c["metadata"]["page"] for c in chunks] == [1, 2]
    assert chunks[0]["content"].startswith("Report: HbA1c (lab report, dated 12 Mar 2026), page 1:")
    assert "7.4 %" in chunks[0]["content"]
    assert "LDL cholesterol 118" in chunks[1]["content"]
    async with clinic.sessionmaker() as session:
        stored = await session.scalar(
            text("select extracted_text from patient_reports where id = :r"), {"r": report_id}
        )
    assert stored.startswith("[Page 1]")


async def test_images_and_scans_are_stored_but_not_searchable(
    client: AsyncClient, clinic: ClinicFixture, ingestion: Ingestion
) -> None:
    s = await Chart(clinic).build()
    image = (await upload(client, s, PNG_BYTES, "Photo")).json()["id"]
    scan = (await upload(client, s, make_blank_pdf(2), "Scan")).json()["id"]
    await ingestion.run()
    for report_id in (image, scan):
        body = (await client.get(f"/api/reports/{report_id}", headers=auth(s.desk.user_id))).json()
        assert body["ingestion_status"] == "no_text", body
        assert body["ingestion_error"]
        assert await chunks_for(clinic, report_id) == []


async def test_failed_extraction_is_recorded_and_retryable(
    client: AsyncClient,
    clinic: ClinicFixture,
    ingestion: Ingestion,
    report_storage: FakeReportStorage,
) -> None:
    s = await Chart(clinic).build()
    broken = b"%PDF-1.4\n" + b"\x00garbage" * 50
    report_id = (await upload(client, s, broken)).json()["id"]
    await ingestion.run()
    failed = (await client.get(f"/api/reports/{report_id}", headers=auth(s.desk.user_id))).json()
    assert failed["ingestion_status"] == "failed"
    assert "could not be read" in failed["ingestion_error"]
    assert await job_statuses(clinic, report_id) == ["done"]  # no automatic retries

    # Fix the stored file (as if re-uploaded by support), then Retry from the UI.
    (path,) = report_storage.files
    report_storage.files[path] = (LAB_PDF, "application/pdf")
    retried = await client.post(f"/api/reports/{report_id}/retry", headers=auth(s.desk.user_id))
    assert retried.status_code == 200
    await ingestion.run()
    fixed = (await client.get(f"/api/reports/{report_id}", headers=auth(s.desk.user_id))).json()
    assert fixed["ingestion_status"] == "indexed"
    assert len(await chunks_for(clinic, report_id)) == 2


async def test_provider_errors_retry_then_fail(
    client: AsyncClient,
    clinic: ClinicFixture,
    ingestion: Ingestion,
    spy_embeddings: SpyEmbeddings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = await Chart(clinic).build()
    report_id = (await upload(client, s, LAB_PDF)).json()["id"]
    spy_embeddings.fail_with = TimeoutError("provider timeout")

    await ingestion.run()
    pending = (await client.get(f"/api/reports/{report_id}", headers=auth(s.desk.user_id))).json()
    assert pending["ingestion_status"] == "pending"
    assert "retrying" in pending["ingestion_error"]
    async with clinic.sessionmaker() as session:
        row = (
            await session.execute(
                text(
                    "select status::text, attempts, last_error, run_after > now() "
                    "from ingestion_jobs where source_id = :r"
                ),
                {"r": report_id},
            )
        ).one()
    assert tuple(row) == ("pending", 1, "TimeoutError", True)  # backed off

    # Last attempt: gives up and shows Failed (Retry button).
    monkeypatch.setattr(get_settings(), "ingestion_max_attempts", 2)
    async with clinic.sessionmaker() as session, session.begin():
        await session.execute(
            text("update ingestion_jobs set run_after = now() where source_id = :r"),
            {"r": report_id},
        )
    await ingestion.run()
    failed = (await client.get(f"/api/reports/{report_id}", headers=auth(s.desk.user_id))).json()
    assert failed["ingestion_status"] == "failed"
    assert await job_statuses(clinic, report_id) == ["failed"]


async def test_background_worker_skips_pytest_clinics(
    client: AsyncClient, clinic: ClinicFixture
) -> None:
    """Tests share the dev database; a running dev server must not take their jobs."""
    s = await Chart(clinic).build()
    consultation_id = await finalized_visit(client, s)
    async with clinic.sessionmaker() as session:
        # Run the worker's own claim in a transaction that is rolled back, with our job made
        # the oldest due job: if it were eligible it would be the one claimed.
        await session.execute(
            text("update ingestion_jobs set run_after = '2000-01-01' where source_id = :c"),
            {"c": consultation_id},
        )
        stale = {"stale": timedelta(minutes=10)}
        claimed = (await session.execute(jobs._ALL_CLINICS, stale)).first()
        await session.rollback()
    assert claimed is None or str(claimed[4]) != consultation_id
    assert await job_statuses(clinic, consultation_id) == ["pending"]


async def test_background_worker_indexes_and_stops_cleanly(
    client: AsyncClient, clinic: ClinicFixture, ingestion: Ingestion
) -> None:
    s = await Chart(clinic).build()
    worker = IngestionWorker(
        clinic.sessionmaker, 0.2, deps_factory=lambda: ingestion.deps, clinic_id=clinic.id
    )
    worker.start()
    worker.start()  # idempotent: still one task
    try:
        consultation_id = await finalized_visit(client, s)
        for _ in range(100):
            if await chunks_for(clinic, consultation_id):
                break
            await asyncio.sleep(0.2)
        assert len(await chunks_for(clinic, consultation_id)) == 1
    finally:
        await worker.stop()
    assert not worker.running
