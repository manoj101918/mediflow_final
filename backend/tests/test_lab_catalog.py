"""Lab test catalog (admin) and the clinic's verification setting."""

from typing import Any

from httpx import AsyncClient

from app.db.models import UserRole
from tests.conftest import ClinicFixture, FakeAuthAdmin, auth


def _test(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "code": "glu",
        "name": "Glucose panel",
        "category": "biochemistry",
        "sample_type": "blood",
        "container": "Fluoride",
        "turnaround_hours": 2,
        "parameters": [
            {
                "code": "fbs",
                "name": "Fasting sugar",
                "unit": "mg/dL",
                "decimals": 0,
                "ranges": [{"low": 70, "high": 100, "critical_low": 40, "critical_high": 450}],
            },
            {
                "code": "ket",
                "name": "Ketones",
                "value_type": "choice",
                "choices": ["Negative", "Positive"],
                "ranges": [{"text_normal": "Negative"}],
            },
        ],
    }
    body.update(overrides)
    return body


async def test_admin_creates_updates_and_deactivates(
    client: AsyncClient, clinic: ClinicFixture
) -> None:
    admin = await clinic.staff(UserRole.ADMIN)
    created = await client.post("/api/admin/lab-tests", json=_test(), headers=auth(admin.user_id))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["code"] == "GLU"
    assert [p["code"] for p in body["parameters"]] == ["FBS", "KET"]
    fbs = body["parameters"][0]
    assert fbs["ranges"][0]["critical_high"] == 450

    # Update: keep FBS (new range), drop KET (deactivated, not deleted), add PPBS.
    update = _test(
        name="Sugar",
        parameters=[
            {**_test()["parameters"][0], "id": fbs["id"], "ranges": [{"low": 70, "high": 110}]},
            {"code": "ppbs", "name": "Post-prandial", "unit": "mg/dL"},
        ],
    )
    r = await client.put(
        f"/api/admin/lab-tests/{body['id']}", json=update, headers=auth(admin.user_id)
    )
    assert r.status_code == 200, r.text
    params = {p["code"]: p for p in r.json()["parameters"]}
    assert params["FBS"]["id"] == fbs["id"]
    assert params["FBS"]["ranges"][0]["high"] == 110
    assert params["KET"]["is_active"] is False
    assert params["PPBS"]["is_active"] is True

    r = await client.patch(
        f"/api/admin/lab-tests/{body['id']}", json={"is_active": False}, headers=auth(admin.user_id)
    )
    assert r.json()["is_active"] is False


async def test_duplicate_code_and_validation(client: AsyncClient, clinic: ClinicFixture) -> None:
    admin = await clinic.staff(UserRole.ADMIN)
    headers = auth(admin.user_id)
    assert (
        await client.post("/api/admin/lab-tests", json=_test(), headers=headers)
    ).status_code == 201
    dup = await client.post("/api/admin/lab-tests", json=_test(), headers=headers)
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "ALREADY_EXISTS"

    bad_range = _test(
        code="X1",
        parameters=[
            {"code": "a", "name": "A", "ranges": [{"low": 5, "high": 10, "critical_low": 6}]}
        ],
    )
    assert (
        await client.post("/api/admin/lab-tests", json=bad_range, headers=headers)
    ).status_code == 422
    no_choices = _test(code="X2", parameters=[{"code": "a", "name": "A", "value_type": "choice"}])
    assert (
        await client.post("/api/admin/lab-tests", json=no_choices, headers=headers)
    ).status_code == 422


async def test_only_admin_manages_catalog(client: AsyncClient, clinic: ClinicFixture) -> None:
    for role in (
        UserRole.RECEPTIONIST,
        UserRole.DOCTOR,
        UserRole.LAB_TECHNICIAN,
        UserRole.LAB_SUPERVISOR,
    ):
        user = await clinic.staff(role)
        r = await client.get("/api/admin/lab-tests", headers=auth(user.user_id))
        assert r.status_code == 403, role


async def test_other_clinic_test_is_not_found(
    client: AsyncClient, clinic: ClinicFixture, other_clinic: ClinicFixture
) -> None:
    tests = await other_clinic.add_lab_catalog()
    admin = await clinic.staff(UserRole.ADMIN)
    r = await client.patch(
        f"/api/admin/lab-tests/{tests['CBC']}",
        json={"is_active": False},
        headers=auth(admin.user_id),
    )
    assert r.status_code == 404


async def test_starter_catalog_is_idempotent(client: AsyncClient, clinic: ClinicFixture) -> None:
    first = await clinic.add_lab_catalog()
    assert {"CBC", "HBA1C", "LIPID", "THYROID", "ELEC", "URINE", "NS1"} <= set(first)
    assert await clinic.add_lab_catalog() == first
    admin = await clinic.staff(UserRole.ADMIN)
    listed = (await client.get("/api/admin/lab-tests", headers=auth(admin.user_id))).json()
    hb = next(p for t in listed if t["code"] == "CBC" for p in t["parameters"] if p["code"] == "HB")
    assert {r["sex"] for r in hb["ranges"]} == {"male", "female"}


async def test_verification_setting(client: AsyncClient, clinic: ClinicFixture) -> None:
    admin = await clinic.staff(UserRole.ADMIN)
    headers = auth(admin.user_id)
    assert (await client.get("/api/admin/clinic-settings", headers=headers)).json() == {
        "lab_requires_verification": True
    }
    r = await client.put(
        "/api/admin/clinic-settings", json={"lab_requires_verification": False}, headers=headers
    )
    assert r.json() == {"lab_requires_verification": False}


async def test_admin_creates_lab_logins(
    client: AsyncClient, clinic: ClinicFixture, auth_admin: FakeAuthAdmin
) -> None:
    admin = await clinic.staff(UserRole.ADMIN)
    for role in ("lab_technician", "lab_supervisor"):
        r = await client.post(
            "/api/admin/users",
            json={
                "email": f"{role}@lab.test",
                "password": "Secret#123",
                "full_name": "Lab",
                "role": role,
            },
            headers=auth(admin.user_id),
        )
        assert r.status_code == 201, r.text
        me = await client.get("/api/me", headers=auth(r.json()["id"]))
        assert me.json()["role"] == role
