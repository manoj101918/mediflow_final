"""Completing a visit finalizes its consultation in the same transaction."""

import pytest
from httpx import AsyncClient

from app.services.records import consultations
from tests.conftest import ClinicFixture, auth
from tests.records_utils import Chart


async def test_complete_finalizes_draft_and_queues_indexing(
    client: AsyncClient, clinic: ClinicFixture
) -> None:
    s = await Chart(clinic).build()
    await s.write(client, s.visit, s.doc_a.user_id)
    done = await s.complete(client, s.visit, s.doc_a.user_id)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["appointment_status"] == "completed"
    assert body["finalized"] is True
    status = await s.scalar(
        "select status::text || '/' || (finalized_at is not null)::text from consultations "
        "where appointment_id = :a",
        a=s.visit,
    )
    assert status == "finalized/true"
    jobs = await s.scalar(
        "select count(*) from ingestion_jobs where source_type = 'consultation' and source_id = :c",
        c=body["consultation_id"],
    )
    assert jobs == 1


async def test_complete_without_consultation_is_allowed(
    client: AsyncClient, clinic: ClinicFixture
) -> None:
    s = await Chart(clinic).build()
    done = await s.complete(client, s.visit, s.doc_a.user_id)
    assert done.status_code == 200
    assert done.json() == {
        "appointment_id": str(s.visit),
        "appointment_status": "completed",
        "consultation_id": None,
        "finalized": False,
    }


async def test_failed_status_change_leaves_draft(
    client: AsyncClient, clinic: ClinicFixture
) -> None:
    s = await Chart(clinic).build()
    checked_in = await clinic.add_appointment(s.doctor_a, s.sunita, status="checked_in")
    await s.write(client, checked_in, s.doc_a.user_id)
    # checked_in -> completed is not an allowed transition (start the consultation first).
    failed = await s.complete(client, checked_in, s.doc_a.user_id)
    assert failed.status_code == 409
    status = await s.scalar(
        "select status::text from consultations where appointment_id = :a", a=checked_in
    )
    assert status == "draft"


async def test_completion_is_atomic(
    client: AsyncClient, clinic: ClinicFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If anything after the status change fails, neither the status nor the draft changes."""
    s = await Chart(clinic).build()
    await s.write(client, s.visit, s.doc_a.user_id)

    async def broken_enqueue(*_: object, **__: object) -> None:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(consultations, "enqueue", broken_enqueue)
    with pytest.raises(RuntimeError):
        await s.complete(client, s.visit, s.doc_a.user_id)
    appointment = await s.scalar("select status::text from appointments where id = :a", a=s.visit)
    consultation = await s.scalar(
        "select status::text from consultations where appointment_id = :a", a=s.visit
    )
    assert (appointment, consultation) == ("in_consultation", "draft")


async def test_reception_completing_also_finalizes(
    client: AsyncClient, clinic: ClinicFixture
) -> None:
    s = await Chart(clinic).build()
    await s.write(client, s.visit, s.doc_a.user_id)
    done = await client.post(
        f"/api/appointments/{s.visit}/status",
        json={"status": "completed"},
        headers=auth(s.desk.user_id),
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed"
    status = await s.scalar(
        "select status::text from consultations where appointment_id = :a", a=s.visit
    )
    assert status == "finalized"


async def test_other_doctor_cannot_complete(client: AsyncClient, clinic: ClinicFixture) -> None:
    s = await Chart(clinic).build()
    assert (await s.complete(client, s.visit, s.doc_b.user_id)).status_code == 404
