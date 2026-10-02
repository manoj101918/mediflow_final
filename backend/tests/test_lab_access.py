"""Who can see what: lab staff get only what testing needs; reception never sees values."""

import pytest
from httpx import AsyncClient

from app.db.models import UserRole
from tests.conftest import ClinicFixture, auth
from tests.lab_utils import LabWorld


@pytest.fixture
async def lab(clinic: ClinicFixture, client: AsyncClient) -> LabWorld:
    return await LabWorld(clinic, client).build()


async def test_lab_staff_cannot_open_clinical_records(lab: LabWorld) -> None:
    detail = await lab.released({"HBA1C": {"HBA1C": 6.9}})
    report_id = detail["order"]["report_id"]
    for user in (lab.tech, lab.head):
        h = auth(user.user_id)
        c = lab.client
        assert (await c.get(f"/api/patients/{lab.ravi}/chart", headers=h)).status_code == 403
        assert (
            await c.get(f"/api/patients/{lab.ravi}/consultations", headers=h)
        ).status_code == 403
        assert (await c.get(f"/api/patients/{lab.ravi}/medications", headers=h)).status_code == 403
        assert (
            await c.get(f"/api/appointments/{lab.visit}/consultation", headers=h)
        ).status_code == 403
        assert (
            await c.put(f"/api/patients/{lab.ravi}/medical-profile", json={}, headers=h)
        ).status_code == 403
        assert (await c.get(f"/api/reports/{report_id}/url", headers=h)).status_code == 403
        assert (
            await c.get(f"/api/patients/{lab.ravi}/chat/sessions", headers=h)
        ).status_code == 403
        r = await c.post(
            f"/api/patients/{lab.ravi}/chat", json={"message": "Any allergy?"}, headers=h
        )
        assert r.status_code == 403
        # Doctor-side lab views are for doctors.
        assert (await c.get(f"/api/patients/{lab.ravi}/lab-results", headers=h)).status_code == 403
        assert (await c.get(f"/api/patients/{lab.ravi}/lab-trends", headers=h)).status_code == 403
        assert (await c.get("/api/lab/inbox", headers=h)).status_code == 403
        assert (await c.get(f"/api/patients/{lab.ravi}/lab-orders", headers=h)).status_code == 403


async def test_lab_sees_identifiers_note_and_same_test_history(lab: LabWorld) -> None:
    created = await lab.ordered("HBA1C", clinical_note="Diabetic, on metformin")
    detail = await lab.detail(created["id"])
    assert detail["patient"] == {
        "id": str(lab.ravi),
        "full_name": "Ravi Kumar",
        "phone": "+919848012345",
        "gender": "male",
        "age": 56,
    }
    assert detail["order"]["clinical_note"] == "Diabetic, on metformin"
    assert detail["order"]["ordering_doctor_name"]
    assert detail["requires_verification"] is True


async def test_reception_and_admin_never_see_values(lab: LabWorld) -> None:
    detail = await lab.released({"HBA1C": {"HBA1C": 6.9}})
    order_id = detail["order"]["id"]
    for user in (lab.desk, lab.admin):
        h = auth(user.user_id)
        c = lab.client
        assert (await c.get(f"/api/patients/{lab.ravi}/lab-results", headers=h)).status_code == 403
        assert (await c.get(f"/api/lab/orders/{order_id}", headers=h)).status_code == 403
        assert (await c.get("/api/lab/worklist", headers=h)).status_code == 403
        assert (await c.get("/api/lab/alerts", headers=h)).status_code == 403
        r = await c.get(f"/api/patients/{lab.ravi}/lab-orders", headers=h)
        assert r.status_code == 200
        assert "6.9" not in r.text


async def test_any_clinic_doctor_reads_results(lab: LabWorld) -> None:
    await lab.released({"HBA1C": {"HBA1C": 6.9}})
    r = await lab.client.get(
        f"/api/patients/{lab.ravi}/lab-results", headers=auth(lab.doc_b.user_id)
    )
    assert r.json()[0]["items"][0]["results"][0]["value_numeric"] == 6.9
    trends = await lab.client.get(
        f"/api/patients/{lab.ravi}/lab-trends", headers=auth(lab.doc_b.user_id)
    )
    [series] = trends.json()
    assert (series["code"], [p["value"] for p in series["points"]]) == ("HBA1C", [6.9])


async def test_other_clinics_are_isolated(lab: LabWorld, other_clinic: ClinicFixture) -> None:
    created = await lab.ordered("CBC")
    outsiders = {
        role: await other_clinic.staff(role)
        for role in (UserRole.DOCTOR, UserRole.LAB_TECHNICIAN, UserRole.LAB_SUPERVISOR)
    }
    doc = auth(outsiders[UserRole.DOCTOR].user_id)
    tech = auth(outsiders[UserRole.LAB_TECHNICIAN].user_id)
    c = lab.client
    assert (await c.get(f"/api/patients/{lab.ravi}/lab-results", headers=doc)).status_code == 404
    assert (await c.get(f"/api/lab/orders/{created['id']}", headers=tech)).status_code == 404
    r = await c.post(
        f"/api/lab/orders/{created['id']}/collect",
        json={"item_ids": [created["items"][0]["id"]]},
        headers=tech,
    )
    assert r.status_code == 404
    r = await c.get("/api/lab/worklist", headers=tech)
    assert r.json() == []
    r = await c.post(f"/api/lab/orders/{created['id']}/cancel", json={"reason": "x"}, headers=tech)
    assert r.status_code == 404
