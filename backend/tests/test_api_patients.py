from httpx import AsyncClient

from app.db.models import UserRole
from tests.conftest import ClinicFixture, auth


async def test_create_normalizes_phone_and_validates(
    client: AsyncClient, clinic: ClinicFixture
) -> None:
    desk = await clinic.staff()
    h = auth(desk.user_id)
    created = await client.post(
        "/api/patients",
        json={
            "full_name": "  Priya Reddy ",
            "phone": "99123 45670",
            "gender": "female",
            "age_years": 30,
            "address": "",
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["full_name"] == "Priya Reddy"
    assert body["phone"] == "+919912345670"
    assert body["age"] == 30
    assert body["address"] is None

    bad_phone = await client.post(
        "/api/patients", json={"full_name": "X", "phone": "12345"}, headers=h
    )
    assert bad_phone.status_code == 422
    assert bad_phone.json()["error"]["message"] == "Enter a valid phone number."

    future_dob = await client.post(
        "/api/patients",
        json={"full_name": "X", "phone": "9912345670", "date_of_birth": "2999-01-01"},
        headers=h,
    )
    assert future_dob.status_code == 422


async def test_patients_are_front_desk_only(client: AsyncClient, clinic: ClinicFixture) -> None:
    doctor = await clinic.staff(UserRole.DOCTOR)
    assert (await client.get("/api/patients", headers=auth(doctor.user_id))).status_code == 403


async def test_search_by_name_and_phone(client: AsyncClient, clinic: ClinicFixture) -> None:
    desk = await clinic.staff()
    await clinic.add_patient("Ravi Kumar", "+919848012345")
    await clinic.add_patient("Lakshmi Narayanan", "+919845098450")
    await clinic.add_patient("Ravindra Jadeja", "+919811112222")
    h = auth(desk.user_id)

    async def names(q: str) -> list[str]:
        r = await client.get("/api/patients", params={"q": q}, headers=h)
        assert r.status_code == 200, r.text
        return [p["full_name"] for p in r.json()["items"]]

    assert await names("ravi") == ["Ravi Kumar", "Ravindra Jadeja"]
    assert await names("Laxmi Narayanan") == ["Lakshmi Narayanan"]  # typo-tolerant
    assert await names("laxmi") == ["Lakshmi Narayanan"]  # one misspelt word
    assert await names("narayan") == ["Lakshmi Narayanan"]  # partial surname
    assert await names("98450") == ["Lakshmi Narayanan"]
    assert await names("+91 98480 12345") == ["Ravi Kumar"]

    page = await client.get("/api/patients", params={"page_size": 2}, headers=h)
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 2


async def test_duplicate_warnings(client: AsyncClient, clinic: ClinicFixture) -> None:
    desk = await clinic.staff()
    ravi = await clinic.add_patient("Ravi Kumar", "+919848012345")
    await clinic.add_patient("Sunita Kumar", "+919848012345")
    h = auth(desk.user_id)

    r = await client.get(
        "/api/patients/duplicates",
        params={"phone": "9848012345", "full_name": "Ravi Kumaar"},
        headers=h,
    )
    reasons = {d["patient"]["full_name"]: d["reason"] for d in r.json()}
    assert reasons == {"Ravi Kumar": "same_phone_similar_name", "Sunita Kumar": "same_phone"}

    by_name = await client.get(
        "/api/patients/duplicates", params={"full_name": "ravi kumar"}, headers=h
    )
    assert [d["reason"] for d in by_name.json()] == ["similar_name"]

    excluded = await client.get(
        "/api/patients/duplicates",
        params={"full_name": "Ravi Kumar", "exclude_id": str(ravi)},
        headers=h,
    )
    assert excluded.json() == []


async def test_detail_and_update(client: AsyncClient, clinic: ClinicFixture) -> None:
    desk = await clinic.staff()
    patient = await clinic.add_patient("Ravi Kumar", "+919848012345")
    h = auth(desk.user_id)

    detail = await client.get(f"/api/patients/{patient}", headers=h)
    assert detail.status_code == 200
    assert detail.json()["appointments"] == []

    patched = await client.patch(
        f"/api/patients/{patient}",
        json={"alternate_phone": "9000000001", "notes": "Allergic to penicillin"},
        headers=h,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["alternate_phone"] == "+919000000001"
    assert patched.json()["full_name"] == "Ravi Kumar"  # untouched

    cleared = await client.patch(f"/api/patients/{patient}", json={"notes": None}, headers=h)
    assert cleared.json()["notes"] is None
    no_phone = await client.patch(f"/api/patients/{patient}", json={"phone": None}, headers=h)
    assert no_phone.status_code == 422

    other_clinic = await client.get("/api/patients/00000000-0000-4000-8000-000000000000", headers=h)
    assert other_clinic.status_code == 404
