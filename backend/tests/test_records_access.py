"""Who can read and write clinical records."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.models import UserRole
from tests.conftest import ClinicFixture, FakeReportStorage, auth
from tests.records_utils import Chart


async def test_any_clinic_doctor_reads_full_chart(
    client: AsyncClient, clinic: ClinicFixture
) -> None:
    s = await Chart(clinic).build()
    assert (await s.write(client, s.visit, s.doc_a.user_id)).status_code == 200
    assert (await s.complete(client, s.visit, s.doc_a.user_id)).status_code == 200

    # doc_c never saw Ravi, yet reads everything, including doc_a's visit and prescription.
    headers = auth(s.doc_c.user_id)
    chart = await client.get(f"/api/patients/{s.ravi}/chart", headers=headers)
    assert chart.status_code == 200, chart.text
    assert chart.json()["full_name"] == "Ravi Kumar"
    assert chart.json()["visit_count"] == 1
    assert "phone" not in chart.json()

    history = (await client.get(f"/api/patients/{s.ravi}/consultations", headers=headers)).json()
    assert len(history) == 1
    assert history[0]["diagnosis"] == "Type 2 diabetes mellitus"
    assert history[0]["items"][0]["medicine_name"] == "Metformin"
    assert history[0]["vitals"]["bp_systolic"] == 140

    meds = (await client.get(f"/api/patients/{s.ravi}/medications", headers=headers)).json()
    assert [m["item"]["medicine_name"] for m in meds] == ["Metformin"]
    vitals = (await client.get(f"/api/patients/{s.ravi}/vitals", headers=headers)).json()
    assert vitals[0]["vitals"]["weight_kg"] == 78.5
    latest = await client.get(f"/api/patients/{s.ravi}/prescriptions/latest", headers=headers)
    assert latest.json()["items"][0]["frequency"] == "1-0-1"


async def test_reception_and_admin_cannot_read_clinical_content(
    client: AsyncClient, clinic: ClinicFixture, report_storage: FakeReportStorage
) -> None:
    s = await Chart(clinic).build()
    await s.write(client, s.visit, s.doc_a.user_id)
    consultation_id = await s.scalar(
        "select id from consultations where appointment_id = :a", a=s.visit
    )
    for user in (s.desk.user_id, s.admin.user_id):
        headers = auth(user)
        for path in (
            f"/api/patients/{s.ravi}/chart",
            f"/api/patients/{s.ravi}/consultations",
            f"/api/patients/{s.ravi}/medications",
            f"/api/patients/{s.ravi}/vitals",
            f"/api/patients/{s.ravi}/prescriptions/latest",
            f"/api/appointments/{s.visit}/consultation",
        ):
            response = await client.get(path, headers=headers)
            assert response.status_code == 403, (path, response.text)
        writes = [
            await client.put(
                f"/api/patients/{s.ravi}/medical-profile",
                json={"allergies": ["Penicillin"]},
                headers=headers,
            ),
            await client.put(
                f"/api/appointments/{s.visit}/consultation",
                json={"diagnosis": "x"},
                headers=headers,
            ),
            await client.post(
                f"/api/consultations/{consultation_id}/addenda",
                json={"text": "x"},
                headers=headers,
            ),
        ]
        assert [w.status_code for w in writes] == [403, 403, 403]


async def test_unknown_or_other_clinic_patient_is_not_found(
    client: AsyncClient, clinic: ClinicFixture, other_clinic: ClinicFixture
) -> None:
    s = await Chart(clinic).build()
    stranger = await other_clinic.add_patient("Other Clinic Patient", "+919800000099")
    outsider = await other_clinic.staff(UserRole.DOCTOR)
    headers = auth(s.doc_a.user_id)
    assert (await client.get(f"/api/patients/{stranger}/chart", headers=headers)).status_code == 404
    assert (
        await client.get(f"/api/patients/{uuid.uuid4()}/chart", headers=headers)
    ).status_code == 404
    # A doctor of another clinic cannot see this clinic's patient.
    other = await client.get(f"/api/patients/{s.ravi}/chart", headers=auth(outsider.user_id))
    assert other.status_code == 404
    assert (
        await client.get(
            f"/api/appointments/{s.visit}/consultation", headers=auth(outsider.user_id)
        )
    ).status_code == 404


async def test_only_the_appointments_doctor_writes_the_visit(
    client: AsyncClient, clinic: ClinicFixture
) -> None:
    s = await Chart(clinic).build()
    other_doctor = await s.write(client, s.visit, s.doc_b.user_id)
    assert other_doctor.status_code == 404
    own = await s.write(client, s.visit, s.doc_a.user_id)
    assert own.status_code == 200, own.text
    assert own.json()["editable"] is True
    # doc_b can read it but sees it as not editable.
    seen = await client.get(
        f"/api/appointments/{s.visit}/consultation", headers=auth(s.doc_b.user_id)
    )
    assert seen.status_code == 200
    assert seen.json()["editable"] is False
    assert seen.json()["consultation"]["diagnosis"] == "Type 2 diabetes mellitus"


async def test_notes_only_while_checked_in_or_in_consultation(
    client: AsyncClient, clinic: ClinicFixture
) -> None:
    s = await Chart(clinic).build()
    scheduled = await clinic.add_appointment(s.doctor_a, s.sunita, status="scheduled")
    response = await s.write(client, scheduled, s.doc_a.user_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_TRANSITION"
    checked_in = await clinic.add_appointment(s.doctor_a, s.sunita, status="checked_in")
    assert (await s.write(client, checked_in, s.doc_a.user_id)).status_code == 200


async def test_draft_autosave_changes_only_sent_fields(
    client: AsyncClient, clinic: ClinicFixture
) -> None:
    s = await Chart(clinic).build()
    await s.write(client, s.visit, s.doc_a.user_id)
    partial = await s.write(client, s.visit, s.doc_a.user_id, advice="Review in 2 weeks")
    body = partial.json()["consultation"]
    assert body["advice"] == "Review in 2 weeks"
    assert body["diagnosis"] == "Type 2 diabetes mellitus"
    assert len(body["items"]) == 1  # items not sent -> unchanged
    cleared = await s.write(client, s.visit, s.doc_a.user_id, items=[])
    assert cleared.json()["consultation"]["items"] == []
    invalid = await s.write(client, s.visit, s.doc_a.user_id, vitals={"bp_systolic": 900})
    assert invalid.status_code == 422


async def test_finalized_consultation_is_read_only_and_addenda_work(
    client: AsyncClient, clinic: ClinicFixture
) -> None:
    s = await Chart(clinic).build()
    await s.write(client, s.visit, s.doc_a.user_id)
    consultation_id = await s.scalar(
        "select id from consultations where appointment_id = :a", a=s.visit
    )
    early = await client.post(
        f"/api/consultations/{consultation_id}/addenda",
        json={"text": "Too early"},
        headers=auth(s.doc_a.user_id),
    )
    assert early.status_code == 409  # drafts are edited directly

    assert (await s.complete(client, s.visit, s.doc_a.user_id)).status_code == 200
    locked = await s.write(client, s.visit, s.doc_a.user_id, diagnosis="Changed")
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "RECORD_LOCKED"

    added = await client.post(
        f"/api/consultations/{consultation_id}/addenda",
        json={"text": "  HbA1c report received: 7.4%  "},
        headers=auth(s.doc_b.user_id),
    )
    assert added.status_code == 201, added.text
    assert added.json()["text"] == "HbA1c report received: 7.4%"
    history = (
        await client.get(f"/api/patients/{s.ravi}/consultations", headers=auth(s.doc_c.user_id))
    ).json()
    assert history[0]["addenda"][0]["author_name"] == "Test doctor"
    assert history[0]["diagnosis"] == "Type 2 diabetes mellitus"
    # The addendum re-queues the visit for the chatbot.
    pending = await s.scalar(
        "select count(*) from ingestion_jobs where source_id = :c and status = 'pending'",
        c=consultation_id,
    )
    assert pending == 1


async def test_database_rejects_edits_to_finalized_consultations(
    client: AsyncClient, clinic: ClinicFixture
) -> None:
    """The trigger backstop holds even if the service check were bypassed."""
    s = await Chart(clinic).build()
    await s.write(client, s.visit, s.doc_a.user_id)
    await s.complete(client, s.visit, s.doc_a.user_id)
    async with clinic.sessionmaker() as session:
        with pytest.raises(DBAPIError, match="finalized"):
            await session.execute(
                text("update consultations set diagnosis = 'x' where appointment_id = :a"),
                {"a": s.visit},
            )


async def test_medical_profile_by_doctors(client: AsyncClient, clinic: ClinicFixture) -> None:
    s = await Chart(clinic).build()
    saved = await client.put(
        f"/api/patients/{s.ravi}/medical-profile",
        json={
            "blood_group": "B+",
            "allergies": [" Penicillin ", "penicillin", "Sulfa drugs", ""],
            "chronic_conditions": ["Type 2 diabetes"],
        },
        headers=auth(s.doc_c.user_id),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["allergies"] == ["Penicillin", "Sulfa drugs"]
    chart = await client.get(f"/api/patients/{s.ravi}/chart", headers=auth(s.doc_a.user_id))
    assert chart.json()["profile"]["blood_group"] == "B+"
    bad = await client.put(
        f"/api/patients/{s.ravi}/medical-profile",
        json={"blood_group": "C+"},
        headers=auth(s.doc_a.user_id),
    )
    assert bad.status_code == 422
    jobs = await s.scalar(
        "select count(*) from ingestion_jobs where source_type = 'profile' and source_id = :p",
        p=s.ravi,
    )
    assert jobs == 1


async def test_chart_opens_are_logged(client: AsyncClient, clinic: ClinicFixture) -> None:
    s = await Chart(clinic).build()
    response = await client.get(
        f"/api/patients/{s.ravi}/chart",
        params={"appointment": str(s.visit)},
        headers=auth(s.doc_a.user_id),
    )
    assert response.json()["appointment"]["id"] == str(s.visit)
    logged = await s.scalar(
        "select count(*) from patient_record_access_log where patient_id = :p "
        "and user_id = :u and action = 'chart_open' and appointment_id = :a",
        p=s.ravi,
        u=s.doc_a.user_id,
        a=s.visit,
    )
    assert logged == 1
