import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.db.models import Appointment, InboundBookingRequest, UserRole
from tests.api_utils import EVERY_DAY, TOMORROW, at
from tests.conftest import ClinicFixture, auth

Sessions = async_sessionmaker[AsyncSession]
URL = "/api/bookings/inbound"
KEY = get_settings().inbound_api_key.get_secret_value()


@pytest.fixture(autouse=True)
def _fresh_limits() -> Iterator[None]:
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def inbound(clinic: ClinicFixture, monkeypatch: pytest.MonkeyPatch) -> ClinicFixture:
    """Route inbound bookings to this test's clinic."""
    monkeypatch.setattr(get_settings(), "inbound_clinic_id", clinic.id)
    return clinic


def payload(doctor: uuid.UUID | None, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "channel": "whatsapp",
        "external_ref": f"wamid.{uuid.uuid4().hex}",
        "caller_phone": "98480 12345",
        "patient_name": "Ravi Kumar",
        "doctor_id": str(doctor) if doctor else None,
        "requested_time": at(9),
        "reason": "Fever since yesterday",
    }
    body.update(overrides)
    return body


async def post(client: AsyncClient, body: Any, key: str | None = KEY) -> Response:
    headers = {"X-API-Key": key} if key is not None else {}
    return await client.post(URL, json=body, headers=headers)


async def count(
    sessionmaker: Sessions,
    model: type[Appointment] | type[InboundBookingRequest],
    clinic: ClinicFixture,
) -> int:
    async with sessionmaker() as session:
        return (
            await session.scalar(
                select(func.count()).select_from(model).where(model.clinic_id == clinic.id)
            )
            or 0
        )


async def test_requires_valid_api_key(
    client: AsyncClient, inbound: ClinicFixture, sessionmaker: Sessions
) -> None:
    doctor = await inbound.add_doctor(weekdays=EVERY_DAY)
    for key in (None, "wrong-key"):
        r = await post(client, payload(doctor), key)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_API_KEY"
    assert await count(sessionmaker, InboundBookingRequest, inbound) == 0


async def test_books_pending_and_retries_are_idempotent(
    client: AsyncClient, inbound: ClinicFixture, sessionmaker: Sessions
) -> None:
    doctor = await inbound.add_doctor(weekdays=EVERY_DAY, name="Dr. Bot Target")
    body = payload(doctor)

    first = await post(client, body)
    assert first.status_code == 201, first.text
    data = first.json()
    assert data["status"] == "auto_booked"
    assert data["duplicate"] is False
    assert data["appointment"]["status"] == "pending_confirmation"
    assert data["appointment"]["token_number"] == 1
    assert data["appointment"]["doctor_name"] == "Dr. Bot Target"

    again = await post(client, body)
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert again.json()["appointment"]["id"] == data["appointment"]["id"]
    assert await count(sessionmaker, Appointment, inbound) == 1
    assert await count(sessionmaker, InboundBookingRequest, inbound) == 1

    async with sessionmaker() as session:
        appt = await session.get(Appointment, uuid.UUID(data["appointment"]["id"]))
        assert appt is not None
        assert appt.source.value == "whatsapp"
        assert appt.external_ref == body["external_ref"]
        assert appt.created_by is None

    # The front desk confirms it.
    desk = await inbound.staff()
    approved = await client.post(
        f"/api/appointments/{data['appointment']['id']}/approve", headers=auth(desk.user_id)
    )
    assert approved.json()["status"] == "scheduled"


async def test_simultaneous_retries_book_once(
    client: AsyncClient, inbound: ClinicFixture, sessionmaker: Sessions
) -> None:
    doctor = await inbound.add_doctor(weekdays=EVERY_DAY)
    body = payload(doctor)
    results = await asyncio.gather(*(post(client, body) for _ in range(3)))
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1, codes
    assert set(codes) <= {200, 201}
    assert await count(sessionmaker, Appointment, inbound) == 1
    assert await count(sessionmaker, InboundBookingRequest, inbound) == 1


async def test_reuses_existing_patient(
    client: AsyncClient, inbound: ClinicFixture, sessionmaker: Sessions
) -> None:
    doctor = await inbound.add_doctor(weekdays=EVERY_DAY)
    existing = await inbound.add_patient("Ravi Kumar", "+919848012345")
    r = await post(
        client, payload(doctor, patient_name="ravi kumar", caller_phone="+91 98480 12345")
    )
    assert r.status_code == 201
    async with sessionmaker() as session:
        appt = await session.get(Appointment, uuid.UUID(r.json()["appointment"]["id"]))
        assert appt is not None and appt.patient_id == existing


async def test_taken_slot_needs_review_with_suggestions(
    client: AsyncClient, inbound: ClinicFixture, sessionmaker: Sessions
) -> None:
    doctor = await inbound.add_doctor(weekdays=EVERY_DAY)
    desk = await inbound.staff()
    other = await inbound.add_patient("Someone Else", "+919800000009")
    booked = await client.post(
        "/api/appointments",
        json={
            "patient_id": str(other),
            "doctor_id": str(doctor),
            "starts_at": at(9),
            "source": "phone",
        },
        headers=auth(desk.user_id),
    )
    assert booked.status_code == 201

    r = await post(client, payload(doctor))
    assert r.status_code == 202, r.text
    data = r.json()
    assert data["status"] == "needs_review"
    assert data["error_code"] == "SLOT_TAKEN"
    assert data["appointment"] is None
    suggested = [s["starts_at"] for s in data["suggested_slots"]]
    assert suggested
    assert suggested[0].startswith(f"{TOMORROW.isoformat()}T03:45:00")  # 09:15 IST

    # The front desk sees it, handles it, and it leaves the review list.
    listed = await client.get("/api/inbound-requests", headers=auth(desk.user_id))
    assert [item["id"] for item in listed.json()] == [data["request_id"]]
    item = listed.json()[0]
    assert item["caller_phone"] == "+919848012345"
    assert item["parsed_patient_name"] == "Ravi Kumar"
    assert item["error"].startswith("SLOT_TAKEN")

    dismissed = await client.post(
        f"/api/inbound-requests/{data['request_id']}/dismiss", headers=auth(desk.user_id)
    )
    assert dismissed.json()["status"] == "rejected"
    assert (await client.get("/api/inbound-requests", headers=auth(desk.user_id))).json() == []

    doctor_user = await inbound.staff(UserRole.DOCTOR)
    forbidden = await client.get("/api/inbound-requests", headers=auth(doctor_user.user_id))
    assert forbidden.status_code == 403


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"doctor_id": None}, "VALIDATION"),
        ({"requested_time": None}, "VALIDATION"),
        ({"doctor_id": "00000000-0000-4000-8000-000000000000"}, "NOT_FOUND"),
        ({"requested_time": at(14)}, "OUTSIDE_SCHEDULE"),
    ],
    ids=["no-doctor", "no-time", "unknown-doctor", "outside-hours"],
)
async def test_incomplete_or_unbookable_requests_need_review(
    client: AsyncClient,
    inbound: ClinicFixture,
    sessionmaker: Sessions,
    overrides: dict[str, Any],
    code: str,
) -> None:
    doctor = await inbound.add_doctor(weekdays=EVERY_DAY)
    r = await post(client, payload(doctor, **overrides))
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "needs_review"
    assert r.json()["error_code"] == code
    assert await count(sessionmaker, Appointment, inbound) == 0


async def test_invalid_content_is_stored_and_rejected(
    client: AsyncClient, inbound: ClinicFixture, sessionmaker: Sessions
) -> None:
    doctor = await inbound.add_doctor(weekdays=EVERY_DAY)

    bad_phone = await post(client, payload(doctor, caller_phone="12345"))
    assert bad_phone.status_code == 422
    request_id = bad_phone.json()["error"]["details"]["request_id"]

    no_name = await post(client, payload(doctor, patient_name=""))
    assert no_name.status_code == 422
    assert no_name.json()["error"]["details"]["errors"][0]["loc"] == ["patient_name"]

    async with sessionmaker() as session:
        stored = await session.get(InboundBookingRequest, uuid.UUID(request_id))
        assert stored is not None
        assert stored.status.value == "rejected"
        assert stored.raw_payload["caller_phone"] == "12345"
    assert await count(sessionmaker, InboundBookingRequest, inbound) == 2


async def test_malformed_requests_are_not_stored(
    client: AsyncClient, inbound: ClinicFixture, sessionmaker: Sessions
) -> None:
    missing_channel = await post(client, {"external_ref": "x", "caller_phone": "9848012345"})
    assert missing_channel.status_code == 422
    not_json = await client.post(
        URL, content=b"not json", headers={"X-API-Key": KEY, "Content-Type": "application/json"}
    )
    assert not_json.status_code == 422
    array = await post(client, [1, 2])
    assert array.status_code == 422
    assert await count(sessionmaker, InboundBookingRequest, inbound) == 0


async def test_rate_limit(
    client: AsyncClient, inbound: ClinicFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "inbound_rate_limit", "3/minute")
    # Rejected keys count too, so the limit also slows down key guessing.
    for _ in range(3):
        assert (await post(client, {}, key="wrong")).status_code == 401
    limited = await post(client, {}, key="wrong")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert int(limited.headers["retry-after"]) > 0
