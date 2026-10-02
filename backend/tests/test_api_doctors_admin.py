from datetime import time

from httpx import AsyncClient

from app.db.models import UserRole
from tests.api_utils import EVERY_DAY, TODAY, TOMORROW, at
from tests.conftest import ClinicFixture, FakeAuthAdmin, auth


async def test_doctor_list_and_slots(client: AsyncClient, clinic: ClinicFixture) -> None:
    desk = await clinic.staff()
    admin = await clinic.staff(UserRole.ADMIN)
    active = await clinic.add_doctor(
        windows=((time(9), time(10)), (time(17), time(18))), weekdays=EVERY_DAY, name="Dr. A"
    )
    await clinic.add_doctor(active=False, name="Dr. Gone")
    await clinic.add_leave(active, TODAY)

    listed = (await client.get("/api/doctors", headers=auth(desk.user_id))).json()
    assert [d["full_name"] for d in listed] == ["Dr. A"]
    assert listed[0]["on_leave_today"] is True
    assert len(listed[0]["schedules"]) == 14

    # Inactive doctors are visible only to admins who ask for them.
    for user, expected in ((desk, 1), (admin, 2)):
        r = await client.get(
            "/api/doctors", params={"include_inactive": "true"}, headers=auth(user.user_id)
        )
        assert len(r.json()) == expected

    slots = await client.get(
        f"/api/doctors/{active}/slots",
        params={"date": TOMORROW.isoformat()},
        headers=auth(desk.user_id),
    )
    assert slots.status_code == 200
    body = slots.json()
    assert body["on_leave"] is False
    assert len(body["slots"]) == 8
    assert body["slots"][0]["starts_at"].startswith(f"{TOMORROW.isoformat()}T03:30:00")

    on_leave = await client.get(
        f"/api/doctors/{active}/slots",
        params={"date": TODAY.isoformat()},
        headers=auth(desk.user_id),
    )
    assert on_leave.json()["on_leave"] is True


async def test_admin_endpoints_are_admin_only(client: AsyncClient, clinic: ClinicFixture) -> None:
    desk = await clinic.staff()
    for method, url in (
        ("GET", "/api/admin/users"),
        ("POST", "/api/admin/doctors"),
        ("DELETE", "/api/admin/leaves/00000000-0000-4000-8000-000000000000"),
    ):
        r = await client.request(method, url, json={}, headers=auth(desk.user_id))
        assert r.status_code == 403, (method, url)


async def test_admin_manages_doctor_schedule_and_leave(
    client: AsyncClient, clinic: ClinicFixture
) -> None:
    admin = await clinic.staff(UserRole.ADMIN)
    desk = await clinic.staff()
    h = auth(admin.user_id)

    created = await client.post(
        "/api/admin/doctors",
        json={"full_name": "Dr. New", "specialization": "ENT", "default_slot_minutes": 20},
        headers=h,
    )
    assert created.status_code == 201, created.text
    doctor_id = created.json()["id"]

    overlap = await client.put(
        f"/api/admin/doctors/{doctor_id}/schedules",
        json={
            "schedules": [
                {"weekday": 0, "start_time": "09:00", "end_time": "12:00"},
                {"weekday": 0, "start_time": "11:00", "end_time": "13:00"},
            ]
        },
        headers=h,
    )
    assert overlap.status_code == 422
    shifts = [{"weekday": wd, "start_time": "09:00", "end_time": "10:00"} for wd in EVERY_DAY]
    saved = await client.put(
        f"/api/admin/doctors/{doctor_id}/schedules", json={"schedules": shifts}, headers=h
    )
    assert saved.status_code == 200
    assert len(saved.json()["schedules"]) == 7

    patient = await clinic.add_patient()
    booked = await client.post(
        "/api/appointments",
        json={
            "patient_id": str(patient),
            "doctor_id": doctor_id,
            "starts_at": at(9, 20),
            "source": "phone",
        },
        headers=auth(desk.user_id),
    )
    assert booked.status_code == 201, booked.text

    leave = await client.post(
        f"/api/admin/doctors/{doctor_id}/leaves",
        json={"leave_date": TOMORROW.isoformat(), "reason": "Conference"},
        headers=h,
    )
    assert leave.status_code == 201
    assert leave.json()["affected_appointments"] == 1
    duplicate = await client.post(
        f"/api/admin/doctors/{doctor_id}/leaves",
        json={"leave_date": TOMORROW.isoformat()},
        headers=h,
    )
    assert duplicate.status_code == 409

    leave_id = leave.json()["id"]
    assert (await client.delete(f"/api/admin/leaves/{leave_id}", headers=h)).status_code == 204
    assert (await client.delete(f"/api/admin/leaves/{leave_id}", headers=h)).status_code == 404

    deactivated = await client.patch(
        f"/api/admin/doctors/{doctor_id}", json={"is_active": False}, headers=h
    )
    assert deactivated.json()["is_active"] is False
    blank = await client.patch(
        f"/api/admin/doctors/{doctor_id}", json={"full_name": None}, headers=h
    )
    assert blank.status_code == 422


async def test_admin_manages_users(
    client: AsyncClient, clinic: ClinicFixture, auth_admin: FakeAuthAdmin
) -> None:
    admin = await clinic.staff(UserRole.ADMIN)
    h = auth(admin.user_id)
    doctor_id = await clinic.add_doctor(name="Dr. Needs Login")
    tag = clinic.id.hex[:6]

    def body(email: str, **extra: str) -> dict[str, str]:
        return {"email": email, "password": "Clinic@12345", "full_name": "Someone", **extra}

    created = await client.post(
        "/api/admin/users",
        json=body(f"Dr.Login-{tag}@MediFlow.test", role="doctor", doctor_id=str(doctor_id)),
        headers=h,
    )
    assert created.status_code == 201, created.text
    user = created.json()
    assert user["email"] == f"dr.login-{tag}@mediflow.test"
    assert user["doctor_id"] == str(doctor_id)

    # The new login resolves to the linked doctor.
    me = await client.get("/api/me", headers=auth(user["id"]))
    assert me.json()["doctor_id"] == str(doctor_id)

    already_linked = await client.post(
        "/api/admin/users",
        json=body(f"other-{tag}@mediflow.test", role="doctor", doctor_id=str(doctor_id)),
        headers=h,
    )
    assert already_linked.status_code == 409

    same_email = await client.post(
        "/api/admin/users", json=body(user["email"], role="receptionist"), headers=h
    )
    assert same_email.status_code == 409

    short_password = await client.post(
        "/api/admin/users",
        json={**body(f"x-{tag}@mediflow.test", role="admin"), "password": "short"},
        headers=h,
    )
    assert short_password.status_code == 422

    listed = (await client.get("/api/admin/users", headers=h)).json()
    assert {u["id"] for u in listed} == {str(admin.user_id), user["id"]}

    off = await client.patch(f"/api/admin/users/{user['id']}", json={"is_active": False}, headers=h)
    assert off.json()["is_active"] is False
    assert (await client.get("/api/me", headers=auth(user["id"]))).status_code == 403

    self_off = await client.patch(
        f"/api/admin/users/{admin.user_id}", json={"is_active": False}, headers=h
    )
    assert self_off.status_code == 422
