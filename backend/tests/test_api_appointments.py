import asyncio
import uuid
from datetime import datetime
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AppointmentSource, UserRole
from app.services.booking import NewAppointment, create_appointment
from tests.api_utils import EVERY_DAY, TODAY, TOMORROW, at
from tests.conftest import ClinicFixture, auth


class Setup:
    """A clinic with a receptionist, two linked doctors (scheduled daily 09-10) and patients."""

    def __init__(self, clinic: ClinicFixture) -> None:
        self.clinic = clinic

    async def build(self) -> "Setup":
        c = self.clinic
        self.desk = await c.staff(UserRole.RECEPTIONIST)
        self.admin = await c.staff(UserRole.ADMIN)
        self.doc_a = await c.staff(UserRole.DOCTOR)
        self.doc_b = await c.staff(UserRole.DOCTOR)
        assert self.doc_a.doctor_id and self.doc_b.doctor_id
        self.doctor_a: uuid.UUID = self.doc_a.doctor_id
        self.doctor_b: uuid.UUID = self.doc_b.doctor_id
        for doctor in (self.doctor_a, self.doctor_b):
            await c.add_schedule(doctor, weekdays=EVERY_DAY)
        self.ravi = await c.add_patient("Ravi Kumar", "+919848012345")
        self.sunita = await c.add_patient("Sunita Rao", "+919848012346")
        return self


async def _book(
    client: AsyncClient,
    user_id: uuid.UUID,
    patient: uuid.UUID,
    doctor: uuid.UUID,
    starts_at: str,
    **extra: Any,
) -> Response:
    body = {
        "patient_id": str(patient),
        "doctor_id": str(doctor),
        "starts_at": starts_at,
        "source": "phone",
        **extra,
    }
    return await client.post("/api/appointments", json=body, headers=auth(user_id))


async def test_receptionist_books_and_lists(client: AsyncClient, clinic: ClinicFixture) -> None:
    s = await Setup(clinic).build()
    created = await _book(
        client, s.desk.user_id, s.ravi, s.doctor_a, at(9), reason_for_visit="  Fever  "
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "scheduled"
    assert body["token_number"] == 1
    assert body["appointment_date"] == TOMORROW.isoformat()
    assert body["reason_for_visit"] == "Fever"
    assert body["patient"]["phone"] == "+919848012345"
    assert body["doctor"]["id"] == str(s.doctor_a)

    listed = await client.get(
        "/api/appointments", params={"date": TOMORROW.isoformat()}, headers=auth(s.desk.user_id)
    )
    assert listed.status_code == 200
    assert [a["id"] for a in listed.json()["items"]] == [body["id"]]
    assert listed.json()["total"] == 1


async def test_front_desk_only_can_book(client: AsyncClient, clinic: ClinicFixture) -> None:
    s = await Setup(clinic).build()
    by_doctor = await _book(client, s.doc_a.user_id, s.ravi, s.doctor_a, at(9))
    assert by_doctor.status_code == 403
    assert by_doctor.json()["error"]["code"] == "FORBIDDEN"
    assert (await _book(client, s.admin.user_id, s.ravi, s.doctor_a, at(9))).status_code == 201


async def test_validation_errors(client: AsyncClient, clinic: ClinicFixture) -> None:
    s = await Setup(clinic).build()
    naive = await _book(client, s.desk.user_id, s.ravi, s.doctor_a, f"{TOMORROW}T09:00:00")
    assert naive.status_code == 422
    assert naive.json()["error"]["code"] == "VALIDATION"

    bot_source = await _book(client, s.desk.user_id, s.ravi, s.doctor_a, at(9), source="whatsapp")
    assert bot_source.status_code == 422

    outside = await _book(client, s.desk.user_id, s.ravi, s.doctor_a, at(14))
    assert outside.status_code == 422
    assert outside.json()["error"]["code"] == "OUTSIDE_SCHEDULE"

    past = await _book(
        client, s.desk.user_id, s.ravi, s.doctor_a, at(9, day=TODAY.replace(year=2020))
    )
    assert past.status_code == 422
    assert past.json()["error"]["code"] == "IN_PAST"

    unknown = await _book(client, s.desk.user_id, uuid.uuid4(), s.doctor_a, at(9))
    assert unknown.status_code == 404


async def test_concurrent_posts_for_same_slot(client: AsyncClient, clinic: ClinicFixture) -> None:
    s = await Setup(clinic).build()
    first, second = await asyncio.gather(
        _book(client, s.desk.user_id, s.ravi, s.doctor_a, at(9, 30)),
        _book(client, s.admin.user_id, s.sunita, s.doctor_a, at(9, 30)),
    )
    assert sorted([first.status_code, second.status_code]) == [201, 409]
    loser = first if first.status_code == 409 else second
    assert loser.json()["error"]["code"] == "SLOT_TAKEN"


async def test_doctor_sees_only_own_appointments_without_phones(
    client: AsyncClient, clinic: ClinicFixture
) -> None:
    s = await Setup(clinic).build()
    mine = (await _book(client, s.desk.user_id, s.ravi, s.doctor_a, at(9))).json()
    theirs = (await _book(client, s.desk.user_id, s.sunita, s.doctor_b, at(9))).json()

    # Asking for another doctor's list still returns only the caller's own appointments.
    listed = await client.get(
        "/api/appointments",
        params={"date": TOMORROW.isoformat(), "doctor_id": str(s.doctor_b)},
        headers=auth(s.doc_a.user_id),
    )
    items = listed.json()["items"]
    assert [a["id"] for a in items] == [mine["id"]]
    assert items[0]["patient"]["phone"] is None

    own = await client.get(f"/api/appointments/{mine['id']}", headers=auth(s.doc_a.user_id))
    assert own.status_code == 200
    other = await client.get(f"/api/appointments/{theirs['id']}", headers=auth(s.doc_a.user_id))
    assert other.status_code == 404

    summary = await client.get(
        "/api/appointments/summary",
        params={"date": TOMORROW.isoformat()},
        headers=auth(s.doc_a.user_id),
    )
    assert summary.json()["total"] == 1


async def test_filters_search_and_summary(client: AsyncClient, clinic: ClinicFixture) -> None:
    s = await Setup(clinic).build()
    a = (await _book(client, s.desk.user_id, s.ravi, s.doctor_a, at(9))).json()
    await _book(client, s.desk.user_id, s.sunita, s.doctor_b, at(9), source="walk_in")
    await client.post(
        f"/api/appointments/{a['id']}/status",
        json={"status": "checked_in"},
        headers=auth(s.desk.user_id),
    )
    day = {"date": TOMORROW.isoformat()}
    h = auth(s.desk.user_id)

    async def ids(**params: Any) -> list[str]:
        r = await client.get("/api/appointments", params={**day, **params}, headers=h)
        assert r.status_code == 200, r.text
        return [item["patient"]["full_name"] for item in r.json()["items"]]

    assert sorted(await ids()) == ["Ravi Kumar", "Sunita Rao"]
    assert await ids(status="checked_in") == ["Ravi Kumar"]
    assert await ids(source="walk_in") == ["Sunita Rao"]
    assert await ids(doctor_id=str(s.doctor_b)) == ["Sunita Rao"]
    assert await ids(q="ravi") == ["Ravi Kumar"]
    assert await ids(q="012346") == ["Sunita Rao"]

    summary = (await client.get("/api/appointments/summary", params=day, headers=h)).json()
    assert summary["total"] == 2
    assert summary["by_status"]["checked_in"] == 1
    assert summary["by_status"]["scheduled"] == 1
    assert summary["by_source"]["walk_in"] == 1

    too_long = await client.get(
        "/api/appointments",
        params={"date_from": "2030-01-01", "date_to": "2030-06-01"},
        headers=h,
    )
    assert too_long.status_code == 422


async def test_status_flow_and_permissions(client: AsyncClient, clinic: ClinicFixture) -> None:
    s = await Setup(clinic).build()
    appt = (await _book(client, s.desk.user_id, s.ravi, s.doctor_a, at(9))).json()
    url = f"/api/appointments/{appt['id']}/status"

    async def move(user_id: uuid.UUID, status: str) -> Response:
        return await client.post(url, json={"status": status}, headers=auth(user_id))

    doctor_checkin = await move(s.doc_a.user_id, "checked_in")
    assert doctor_checkin.status_code == 403
    assert (await move(s.desk.user_id, "completed")).status_code == 409
    assert (await move(s.desk.user_id, "checked_in")).json()["status"] == "checked_in"
    assert (await move(s.doc_b.user_id, "in_consultation")).status_code == 404
    assert (await move(s.doc_a.user_id, "in_consultation")).json()["status"] == "in_consultation"
    assert (await move(s.doc_a.user_id, "completed")).json()["status"] == "completed"

    detail = (
        await client.get(f"/api/appointments/{appt['id']}", headers=auth(s.desk.user_id))
    ).json()
    assert [e["to_status"] for e in detail["events"]] == [
        "scheduled",
        "checked_in",
        "in_consultation",
        "completed",
    ]
    assert detail["events"][-1]["changed_by_name"] == "Test doctor"


async def test_reschedule(client: AsyncClient, clinic: ClinicFixture) -> None:
    s = await Setup(clinic).build()
    appt = (await _book(client, s.desk.user_id, s.ravi, s.doctor_a, at(9))).json()
    await _book(client, s.desk.user_id, s.sunita, s.doctor_a, at(9, 15))
    url = f"/api/appointments/{appt['id']}/reschedule"
    h = auth(s.desk.user_id)

    taken = await client.post(url, json={"starts_at": at(9, 15)}, headers=h)
    assert taken.status_code == 409
    moved = await client.post(url, json={"starts_at": at(9, 45)}, headers=h)
    assert moved.status_code == 200
    assert moved.json()["starts_at"].startswith(f"{TOMORROW.isoformat()}T04:15:00")  # 09:45 IST
    doctor = await client.post(url, json={"starts_at": at(9, 30)}, headers=auth(s.doc_a.user_id))
    assert doctor.status_code == 403


async def test_approve_and_reject_bot_bookings(
    client: AsyncClient,
    clinic: ClinicFixture,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    s = await Setup(clinic).build()
    pending = []
    for minute, patient in ((0, s.ravi), (15, s.sunita)):
        async with sessionmaker() as session:
            result = await create_appointment(
                session,
                NewAppointment(
                    patient,
                    s.doctor_a,
                    datetime.fromisoformat(at(9, minute)),
                    AppointmentSource.WHATSAPP,
                    external_ref=f"wa-{minute}",
                ),
                clinic.system("whatsapp"),
            )
        pending.append(result.unwrap().id)

    h = auth(s.desk.user_id)
    pending_list = await client.get(
        "/api/appointments",
        params={"date": TOMORROW.isoformat(), "status": "pending_confirmation"},
        headers=h,
    )
    assert pending_list.json()["total"] == 2

    approved = await client.post(f"/api/appointments/{pending[0]}/approve", headers=h)
    assert approved.status_code == 200
    assert approved.json()["status"] == "scheduled"
    rejected = await client.post(
        f"/api/appointments/{pending[1]}/reject", json={"reason": "Full"}, headers=h
    )
    assert rejected.json()["status"] == "cancelled"
    again = await client.post(f"/api/appointments/{pending[0]}/approve", headers=h)
    assert again.status_code == 409
    doctor = await client.post(
        f"/api/appointments/{pending[0]}/approve", headers=auth(s.doc_a.user_id)
    )
    assert doctor.status_code == 403
