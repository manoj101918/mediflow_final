"""Row Level Security, checked with real Postgres role switching.

FastAPI bypasses RLS (it connects as the owner), so these policies are what protect Realtime
subscriptions and any direct Supabase access with a user's JWT. Each query runs as the
`authenticated` (or `anon`) role with forged JWT claims inside a transaction that is rolled back.
"""

import json
import uuid
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AppointmentSource, UserRole
from app.services.booking import NewAppointment, create_appointment
from tests.api_utils import EVERY_DAY, at
from tests.conftest import ClinicFixture

Sessions = async_sessionmaker[AsyncSession]


async def _query(
    sessionmaker: Sessions,
    user_id: uuid.UUID | None,
    sql: str,
    params: dict[str, Any] | None = None,
    *,
    role: str = "authenticated",
) -> set[Any]:
    async with sessionmaker() as session:
        try:
            await session.execute(text(f"set local role {role}"))
            if user_id is not None:
                await session.execute(
                    text("select set_config('request.jwt.claims', :claims, true)"),
                    {"claims": json.dumps({"sub": str(user_id), "role": role})},
                )
            return set((await session.execute(text(sql), params or {})).scalars())
        finally:
            await session.rollback()


class World:
    """Two doctors with one appointment each, a receptionist, and an inbound request."""

    async def build(self, clinic: ClinicFixture, sessionmaker: Sessions) -> "World":
        self.desk = await clinic.staff(UserRole.RECEPTIONIST)
        self.doc_a = await clinic.staff(UserRole.DOCTOR)
        self.doc_b = await clinic.staff(UserRole.DOCTOR)
        self.inactive = await clinic.staff(UserRole.RECEPTIONIST)
        async with sessionmaker() as session:
            await session.execute(
                text("update public.profiles set is_active = false where id = :id"),
                {"id": self.inactive.user_id},
            )
            await session.execute(
                text(
                    "insert into public.inbound_booking_requests (clinic_id, channel, raw_payload) "
                    "values (:cid, 'whatsapp', '{}'::jsonb)"
                ),
                {"cid": clinic.id},
            )
            await session.commit()

        self.patient_a = await clinic.add_patient("Patient A", "+919800000001")
        self.patient_b = await clinic.add_patient("Patient B", "+919800000002")
        self.appointments: dict[str, uuid.UUID] = {}
        for key, doc, patient in (
            ("a", self.doc_a, self.patient_a),
            ("b", self.doc_b, self.patient_b),
        ):
            assert doc.doctor_id is not None
            await clinic.add_schedule(doc.doctor_id, weekdays=EVERY_DAY)
            async with sessionmaker() as session:
                result = await create_appointment(
                    session,
                    NewAppointment(
                        patient,
                        doc.doctor_id,
                        datetime.fromisoformat(at(9)),
                        AppointmentSource.PHONE,
                    ),
                    self.desk,
                )
            self.appointments[key] = result.unwrap().id
        return self


@pytest.fixture
async def world(clinic: ClinicFixture, sessionmaker: Sessions) -> World:
    return await World().build(clinic, sessionmaker)


async def test_doctor_sees_only_own_appointments_and_patients(
    sessionmaker: Sessions, clinic: ClinicFixture, world: World
) -> None:
    uid = world.doc_a.user_id
    assert await _query(sessionmaker, uid, "select id from public.appointments") == {
        world.appointments["a"]
    }
    assert await _query(sessionmaker, uid, "select id from public.patients") == {world.patient_a}
    assert await _query(
        sessionmaker, uid, "select appointment_id from public.appointment_events"
    ) == {world.appointments["a"]}
    # Profiles: only their own row. Inbound requests: none.
    assert await _query(sessionmaker, uid, "select id from public.profiles") == {uid}
    assert (
        await _query(sessionmaker, uid, "select id from public.inbound_booking_requests") == set()
    )
    # Reference data of their own clinic only.
    doctors = await _query(sessionmaker, uid, "select clinic_id from public.doctors")
    assert doctors == {clinic.id}


async def test_receptionist_sees_whole_clinic_but_nothing_else(
    sessionmaker: Sessions, clinic: ClinicFixture, world: World
) -> None:
    uid = world.desk.user_id
    assert await _query(sessionmaker, uid, "select id from public.appointments") == set(
        world.appointments.values()
    )
    assert await _query(sessionmaker, uid, "select id from public.patients") == {
        world.patient_a,
        world.patient_b,
    }
    assert len(await _query(sessionmaker, uid, "select id from public.profiles")) == 4
    assert (
        len(await _query(sessionmaker, uid, "select id from public.inbound_booking_requests")) == 1
    )
    # The seeded demo clinic (and any other clinic) is invisible.
    assert await _query(sessionmaker, uid, "select id from public.clinics") == {clinic.id}


@pytest.mark.parametrize("who", ["inactive", "no_profile"])
async def test_inactive_or_unknown_login_sees_nothing(
    sessionmaker: Sessions, clinic: ClinicFixture, world: World, who: str
) -> None:
    uid = world.inactive.user_id if who == "inactive" else await clinic.add_auth_user()
    for table in ("appointments", "patients", "doctors", "clinics", "appointment_events"):
        sql = f"select id from public.{table}"  # noqa: S608 - fixed table names
        assert await _query(sessionmaker, uid, sql) == set(), table


async def test_anon_has_no_table_access(sessionmaker: Sessions, world: World) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        await _query(sessionmaker, None, "select id from public.appointments", role="anon")


async def test_doctor_cannot_write_appointments(
    sessionmaker: Sessions, clinic: ClinicFixture, world: World
) -> None:
    assert world.doc_a.doctor_id is not None
    insert = (
        "insert into public.appointments (clinic_id, patient_id, doctor_id, starts_at, ends_at, "
        "source, token_number) values (:cid, :pid, :did, now() + interval '3 days', "
        "now() + interval '3 days 15 min', 'manual', 99) returning id"
    )
    params = {"cid": clinic.id, "pid": world.patient_a, "did": world.doc_a.doctor_id}
    with pytest.raises(DBAPIError, match="row-level security"):
        await _query(sessionmaker, world.doc_a.user_id, insert, params)

    # Updates without a matching policy silently affect no rows.
    update = "update public.appointments set notes = 'x' where id = :id returning id"
    updated = await _query(
        sessionmaker, world.doc_a.user_id, update, {"id": world.appointments["a"]}
    )
    assert updated == set()
