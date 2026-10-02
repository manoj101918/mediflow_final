"""Report uploads: type and size checks, storage path, who sees what."""

import re
import uuid

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text as sql

from app.core.config import get_settings
from tests.conftest import ClinicFixture, FakeReportStorage, auth
from tests.pdf_utils import PNG_BYTES, make_pdf
from tests.records_utils import Chart

PDF = make_pdf(["HbA1c 7.4 % (ref < 5.7)"])


async def _upload(
    client: AsyncClient,
    user: uuid.UUID,
    patient: uuid.UUID,
    data: bytes,
    *,
    filename: str = "report.pdf",
    content_type: str = "application/pdf",
    **fields: str,
) -> Response:
    form = {"title": "HbA1c", "report_type": "lab", "report_date": "2026-03-12", **fields}
    return await client.post(
        f"/api/patients/{patient}/reports",
        data=form,
        files={"file": (filename, data, content_type)},
        headers=auth(user),
    )


async def test_reception_uploads_pdf(
    client: AsyncClient, clinic: ClinicFixture, report_storage: FakeReportStorage
) -> None:
    s = await Chart(clinic).build()
    response = await _upload(client, s.desk.user_id, s.ravi, PDF)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["ingestion_status"] == "pending"
    assert body["mime_type"] == "application/pdf"
    assert body["size_bytes"] == len(PDF)

    (path,) = report_storage.files
    assert path == f"{clinic.id}/{s.ravi}/{body['id']}.pdf"
    assert re.fullmatch(r"[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f-]{36}\.pdf", path)
    assert report_storage.files[path] == (PDF, "application/pdf")

    jobs = await s.scalar(
        "select count(*) from ingestion_jobs where source_type = 'report' and source_id = :r",
        r=body["id"],
    )
    logged = await s.scalar(
        "select count(*) from patient_record_access_log where report_id = :r "
        "and action = 'report_upload'",
        r=body["id"],
    )
    assert (jobs, logged) == (1, 1)


async def test_png_detected_from_bytes(
    client: AsyncClient, clinic: ClinicFixture, report_storage: FakeReportStorage
) -> None:
    s = await Chart(clinic).build()
    # Declared as PDF, but the bytes are a PNG: the bytes win.
    response = await _upload(client, s.doc_a.user_id, s.ravi, PNG_BYTES)
    assert response.status_code == 201, response.text
    assert response.json()["mime_type"] == "image/png"
    assert next(iter(report_storage.files)).endswith(".png")


async def test_wrong_type_is_rejected(
    client: AsyncClient, clinic: ClinicFixture, report_storage: FakeReportStorage
) -> None:
    s = await Chart(clinic).build()
    response = await _upload(
        client, s.desk.user_id, s.ravi, b"MZ\x90\x00 not a report", filename="x.pdf"
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert report_storage.files == {}


async def test_oversize_is_rejected(
    client: AsyncClient,
    clinic: ClinicFixture,
    report_storage: FakeReportStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = await Chart(clinic).build()
    monkeypatch.setattr(get_settings(), "report_max_mb", 1)
    big = b"%PDF-1.4\n" + b"0" * (1024 * 1024)
    response = await _upload(client, s.desk.user_id, s.ravi, big)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert report_storage.files == {}


async def test_validation_and_unknown_patient(
    client: AsyncClient, clinic: ClinicFixture, report_storage: FakeReportStorage
) -> None:
    s = await Chart(clinic).build()
    assert (await _upload(client, s.desk.user_id, s.ravi, b"")).status_code == 422
    assert (
        await _upload(client, s.desk.user_id, s.ravi, PDF, report_type="xray")
    ).status_code == 422
    assert (await _upload(client, s.desk.user_id, uuid.uuid4(), PDF)).status_code == 404
    other_patients_visit = await clinic.add_appointment(s.doctor_a, s.sunita, status="checked_in")
    await s.write(client, other_patients_visit, s.doc_a.user_id)
    consultation = await s.scalar(
        "select id from consultations where appointment_id = :a", a=other_patients_visit
    )
    wrong_visit = await _upload(
        client, s.doc_a.user_id, s.ravi, PDF, consultation_id=str(consultation)
    )
    assert wrong_visit.status_code == 404
    assert report_storage.files == {}


async def test_reception_sees_metadata_not_contents(
    client: AsyncClient, clinic: ClinicFixture, report_storage: FakeReportStorage
) -> None:
    s = await Chart(clinic).build()
    report_id = (await _upload(client, s.desk.user_id, s.ravi, PDF)).json()["id"]

    listed = await client.get(f"/api/patients/{s.ravi}/reports", headers=auth(s.desk.user_id))
    assert listed.status_code == 200
    assert [r["title"] for r in listed.json()] == ["HbA1c"]
    assert "extracted_text" not in listed.json()[0]
    denied = await client.get(f"/api/reports/{report_id}/url", headers=auth(s.desk.user_id))
    assert denied.status_code == 403

    url = await client.get(f"/api/reports/{report_id}/url", headers=auth(s.doc_c.user_id))
    assert url.status_code == 200, url.text
    assert url.json()["url"].startswith("https://storage.test/")
    assert url.json()["expires_in"] == get_settings().signed_url_ttl_seconds
    views = await s.scalar(
        "select count(*) from patient_record_access_log where report_id = :r "
        "and action = 'report_view' and user_id = :u",
        r=report_id,
        u=s.doc_c.user_id,
    )
    assert views == 1


async def test_retry_only_failed_reports(
    client: AsyncClient, clinic: ClinicFixture, report_storage: FakeReportStorage
) -> None:
    s = await Chart(clinic).build()
    report_id = (await _upload(client, s.desk.user_id, s.ravi, PDF)).json()["id"]
    not_failed = await client.post(f"/api/reports/{report_id}/retry", headers=auth(s.desk.user_id))
    assert not_failed.status_code == 409

    async with clinic.sessionmaker() as session, session.begin():
        await session.execute(
            sql(
                "update patient_reports set ingestion_status = 'failed', ingestion_error = 'x' "
                "where id = :r"
            ),
            {"r": report_id},
        )
        await session.execute(
            sql("update ingestion_jobs set status = 'failed' where source_id = :r"),
            {"r": report_id},
        )
    retried = await client.post(f"/api/reports/{report_id}/retry", headers=auth(s.desk.user_id))
    assert retried.status_code == 200, retried.text
    assert retried.json()["ingestion_status"] == "pending"
    assert retried.json()["ingestion_error"] is None
    pending = await s.scalar(
        "select count(*) from ingestion_jobs where source_id = :r and status = 'pending'",
        r=report_id,
    )
    assert pending == 1
