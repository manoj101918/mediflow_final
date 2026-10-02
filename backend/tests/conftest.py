"""Shared fixtures.

DB tests run against TEST_DATABASE_URL. Each test gets its own throwaway clinic (and auth
users) that is deleted on teardown, so seed data is never modified. API tests replace only the
JWT verifier: the bearer token is simply the auth user's id.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date, time
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.security import InvalidTokenError, TokenClaims, get_jwt_verifier
from app.db.models import UserRole
from app.db.session import build_engine, get_session
from app.main import create_app
from app.services.booking.actor import StaffActor, SystemActor, SystemChannel


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    url = get_settings().test_database_url
    if url is None:
        pytest.skip("TEST_DATABASE_URL is not set")
    test_engine = build_engine(url.get_secret_value())
    yield test_engine
    await test_engine.dispose()


@pytest.fixture(scope="session")
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@dataclass
class ClinicFixture:
    id: UUID
    name: str
    sessionmaker: async_sessionmaker[AsyncSession]
    auth_user_ids: list[UUID] = field(default_factory=list)

    async def add_auth_user(self) -> UUID:
        user_id = uuid.uuid4()
        async with self.sessionmaker() as session, session.begin():
            await session.execute(
                text(
                    "insert into auth.users (id, email, aud, role) "
                    "values (:id, :email, 'authenticated', 'authenticated')"
                ),
                {"id": user_id, "email": f"pytest-{user_id.hex[:12]}@mediflow.test"},
            )
        self.auth_user_ids.append(user_id)
        return user_id

    async def add_user(
        self, role: UserRole, *, active: bool = True, link_doctor: bool = False
    ) -> UUID:
        """Create an auth user + profile; for doctors optionally a linked doctors row."""
        user_id = await self.add_auth_user()
        async with self.sessionmaker() as session, session.begin():
            await session.execute(
                text(
                    "insert into public.profiles (id, clinic_id, full_name, role, is_active) "
                    "values (:id, :clinic_id, :name, cast(:role as public.user_role), :active)"
                ),
                {
                    "id": user_id,
                    "clinic_id": self.id,
                    "name": f"Test {role.value}",
                    "role": role.value,
                    "active": active,
                },
            )
            if link_doctor:
                await session.execute(
                    text(
                        "insert into public.doctors (clinic_id, profile_id, full_name, "
                        "specialization) values (:clinic_id, :pid, 'Dr. Test', 'General')"
                    ),
                    {"clinic_id": self.id, "pid": user_id},
                )
        return user_id

    async def doctor_id_for(self, profile_id: UUID) -> UUID:
        async with self.sessionmaker() as session:
            doctor_id = await session.scalar(
                text("select id from public.doctors where profile_id = :pid"), {"pid": profile_id}
            )
        assert doctor_id is not None
        return UUID(str(doctor_id))

    async def add_doctor(
        self,
        *,
        windows: tuple[tuple[time, time], ...] = ((time(9), time(10)),),
        weekdays: tuple[int, ...] = (0,),
        slot_minutes: int = 15,
        active: bool = True,
        name: str = "Dr. Test",
    ) -> UUID:
        """A doctor with the given schedule windows on each weekday (0 = Monday)."""
        doctor_id = uuid.uuid4()
        async with self.sessionmaker() as session, session.begin():
            await session.execute(
                text(
                    "insert into public.doctors (id, clinic_id, full_name, specialization, "
                    "default_slot_minutes, is_active) values (:id, :cid, :name, 'General', "
                    ":slot, :active)"
                ),
                {
                    "id": doctor_id,
                    "cid": self.id,
                    "name": name,
                    "slot": slot_minutes,
                    "active": active,
                },
            )
            for weekday in weekdays:
                for start, end in windows:
                    await session.execute(
                        text(
                            "insert into public.doctor_schedules (clinic_id, doctor_id, weekday, "
                            "start_time, end_time) values (:cid, :did, :wd, :start, :end)"
                        ),
                        {
                            "cid": self.id,
                            "did": doctor_id,
                            "wd": weekday,
                            "start": start,
                            "end": end,
                        },
                    )
        return doctor_id

    async def add_leave(self, doctor_id: UUID, day: date) -> None:
        async with self.sessionmaker() as session, session.begin():
            await session.execute(
                text(
                    "insert into public.doctor_leaves (clinic_id, doctor_id, leave_date) "
                    "values (:cid, :did, :day)"
                ),
                {"cid": self.id, "did": doctor_id, "day": day},
            )

    async def add_patient(self, name: str = "Test Patient", phone: str = "+919800000001") -> UUID:
        patient_id = uuid.uuid4()
        async with self.sessionmaker() as session, session.begin():
            await session.execute(
                text(
                    "insert into public.patients (id, clinic_id, full_name, phone) "
                    "values (:id, :cid, :name, :phone)"
                ),
                {"id": patient_id, "cid": self.id, "name": name, "phone": phone},
            )
        return patient_id

    async def staff(self, role: UserRole = UserRole.RECEPTIONIST) -> StaffActor:
        """A real staff profile in this clinic, as a booking actor."""
        link = role == UserRole.DOCTOR
        user_id = await self.add_user(role, link_doctor=link)
        doctor_id = await self.doctor_id_for(user_id) if link else None
        return StaffActor(user_id=user_id, role=role, clinic_id=self.id, doctor_id=doctor_id)

    def system(self, channel: SystemChannel = "whatsapp") -> SystemActor:
        return SystemActor(channel=channel, clinic_id=self.id)


@pytest.fixture
async def clinic(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[ClinicFixture]:
    clinic_id = uuid.uuid4()
    name = f"pytest-clinic-{clinic_id.hex[:8]}"
    async with sessionmaker() as session, session.begin():
        await session.execute(
            text("insert into public.clinics (id, name) values (:id, :name)"),
            {"id": clinic_id, "name": name},
        )
    fixture = ClinicFixture(id=clinic_id, name=name, sessionmaker=sessionmaker)
    yield fixture
    async with sessionmaker() as session, session.begin():
        # Clinic delete cascades to every clinic-scoped row; auth users are removed separately.
        await session.execute(text("delete from public.clinics where id = :id"), {"id": clinic_id})
        if fixture.auth_user_ids:
            await session.execute(
                text("delete from auth.users where id = any(:ids)"),
                {"ids": fixture.auth_user_ids},
            )


class FakeVerifier:
    """Treats the bearer token as the auth user id; 'invalid' tokens are rejected."""

    def verify(self, token: str) -> TokenClaims:
        try:
            user_id = UUID(token)
        except ValueError as exc:
            raise InvalidTokenError("bad token") from exc
        return TokenClaims(user_id=user_id, email=f"{token[:8]}@mediflow.test")


@pytest.fixture
def app(sessionmaker: async_sessionmaker[AsyncSession]) -> FastAPI:
    application = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    application.dependency_overrides[get_session] = _session
    application.dependency_overrides[get_jwt_verifier] = FakeVerifier
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


def auth(user_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {user_id}"}
