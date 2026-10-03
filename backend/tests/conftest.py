"""Shared fixtures.

DB tests run against TEST_DATABASE_URL. Each test gets its own throwaway clinic (and auth
users) that is deleted on teardown, so seed data is never modified. API tests replace only the
JWT verifier: the bearer token is simply the auth user's id.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langchain_core.embeddings import Embeddings
from langchain_core.embeddings.fake import DeterministicFakeEmbedding
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.chat import rag_providers
from app.core.config import get_settings
from app.core.rate_limit import reset_chat_limits
from app.core.security import InvalidTokenError, TokenClaims, get_jwt_verifier
from app.db.models import EMBEDDING_DIM, LabTest, UserRole
from app.db.session import build_engine, get_session
from app.deps import get_session_factory
from app.main import create_app
from app.services.booking.actor import StaffActor, SystemActor, SystemChannel
from app.services.ingestion.worker import IngestionDeps, run_pending
from app.services.labs.catalog_seed import install_catalog
from app.services.rag.providers import FakeRecordsChatModel, RagProviders
from app.services.records.storage import get_report_storage
from app.services.users import EmailTakenError, get_auth_admin

if TYPE_CHECKING:
    from tests.whatsapp_utils import WhatsAppHarness


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
    _appointments: int = 0

    async def add_auth_user(self, email: str | None = None) -> UUID:
        user_id = uuid.uuid4()
        async with self.sessionmaker() as session, session.begin():
            await session.execute(
                text(
                    "insert into auth.users (id, email, aud, role) "
                    "values (:id, :email, 'authenticated', 'authenticated')"
                ),
                {"id": user_id, "email": email or f"pytest-{user_id.hex[:12]}@mediflow.test"},
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
        await self.add_schedule(doctor_id, windows=windows, weekdays=weekdays)
        return doctor_id

    async def add_schedule(
        self,
        doctor_id: UUID,
        *,
        windows: tuple[tuple[time, time], ...] = ((time(9), time(10)),),
        weekdays: tuple[int, ...] = (0,),
    ) -> None:
        async with self.sessionmaker() as session, session.begin():
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

    async def add_appointment(
        self,
        doctor_id: UUID,
        patient_id: UUID,
        *,
        status: str = "checked_in",
        starts_at: datetime | None = None,
        minutes: int = 15,
    ) -> UUID:
        """Insert an appointment directly (past dates and any status allowed).

        Each call gets its own non-overlapping slot and token unless starts_at is given.
        """
        self._appointments += 1
        seq = self._appointments
        start = starts_at or datetime(2026, 1, 5, 4, 0, tzinfo=UTC) + timedelta(hours=seq)
        appointment_id = uuid.uuid4()
        async with self.sessionmaker() as session, session.begin():
            await session.execute(
                text(
                    "insert into public.appointments (id, clinic_id, patient_id, doctor_id, "
                    "starts_at, ends_at, status, source, token_number) values (:id, :cid, "
                    ":pid, :did, :start, :end, cast(:status as public.appointment_status), "
                    "'walk_in', :token)"
                ),
                {
                    "id": appointment_id,
                    "cid": self.id,
                    "pid": patient_id,
                    "did": doctor_id,
                    "start": start,
                    "end": start + timedelta(minutes=minutes),
                    "status": status,
                    "token": seq,
                },
            )
        return appointment_id

    async def staff(self, role: UserRole = UserRole.RECEPTIONIST) -> StaffActor:
        """A real staff profile in this clinic, as a booking actor."""
        link = role == UserRole.DOCTOR
        user_id = await self.add_user(role, link_doctor=link)
        doctor_id = await self.doctor_id_for(user_id) if link else None
        return StaffActor(user_id=user_id, role=role, clinic_id=self.id, doctor_id=doctor_id)

    def system(self, channel: SystemChannel = "whatsapp") -> SystemActor:
        return SystemActor(channel=channel, clinic_id=self.id)

    async def add_lab_catalog(self) -> dict[str, UUID]:
        """The starter lab catalog for this clinic; returns test ids by code."""
        async with self.sessionmaker() as session:
            await install_catalog(session, self.id)
            rows = await session.execute(
                select(LabTest.code, LabTest.id).where(LabTest.clinic_id == self.id)
            )
            return {code: test_id for code, test_id in rows}

    async def set_lab_verification(self, required: bool) -> None:
        async with self.sessionmaker() as session, session.begin():
            await session.execute(
                text("update public.clinics set lab_requires_verification = :v where id = :c"),
                {"v": required, "c": self.id},
            )


@asynccontextmanager
async def _throwaway_clinic(
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
    try:
        yield fixture
    finally:
        async with sessionmaker() as session, session.begin():
            # Clinic delete cascades to every clinic-scoped row; auth users go separately.
            await session.execute(
                text("delete from public.clinics where id = :id"), {"id": clinic_id}
            )
            if fixture.auth_user_ids:
                await session.execute(
                    text("delete from auth.users where id = any(:ids)"),
                    {"ids": fixture.auth_user_ids},
                )


@pytest.fixture
async def clinic(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[ClinicFixture]:
    async with _throwaway_clinic(sessionmaker) as fixture:
        yield fixture


@pytest.fixture
async def other_clinic(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[ClinicFixture]:
    """A second, unrelated clinic (cross-clinic isolation tests)."""
    async with _throwaway_clinic(sessionmaker) as fixture:
        yield fixture


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


class FakeAuthAdmin:
    """Stands in for the Supabase Admin API: creates real auth.users rows via the test DB."""

    def __init__(self, clinic: ClinicFixture, loop: asyncio.AbstractEventLoop) -> None:
        self._clinic = clinic
        self._loop = loop
        self.emails: set[str] = set()

    def create_user(self, email: str, password: str) -> UUID:
        if email in self.emails:
            raise EmailTakenError(email)
        self.emails.add(email)
        future = asyncio.run_coroutine_threadsafe(self._clinic.add_auth_user(email), self._loop)
        return future.result(timeout=30)

    def delete_user(self, user_id: UUID) -> None:  # pragma: no cover - only on failures
        pass


@pytest.fixture
async def auth_admin(app: FastAPI, clinic: ClinicFixture) -> FakeAuthAdmin:
    fake = FakeAuthAdmin(clinic, asyncio.get_running_loop())
    app.dependency_overrides[get_auth_admin] = lambda: fake
    return fake


class FakeReportStorage:
    """In-memory stand-in for the Supabase Storage bucket."""

    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}

    def upload(self, path: str, data: bytes, content_type: str, *, upsert: bool = False) -> None:
        if path in self.files and not upsert:
            raise RuntimeError("exists")
        self.files[path] = (data, content_type)

    def download(self, path: str) -> bytes:
        return self.files[path][0]

    def signed_url(self, path: str, expires_in: int) -> str:
        return f"https://storage.test/{path}?expires_in={expires_in}"

    def remove(self, path: str) -> None:
        self.files.pop(path, None)


@pytest.fixture
def report_storage(app: FastAPI) -> FakeReportStorage:
    fake = FakeReportStorage()
    app.dependency_overrides[get_report_storage] = lambda: fake
    return fake


TEST_EMBEDDING_MODEL = "pytest-fake"


class SpyEmbeddings(Embeddings):
    """Deterministic fake embeddings that count how many texts were embedded."""

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self._fake = DeterministicFakeEmbedding(size=dim)
        self.embedded: list[str] = []
        self.fail_with: Exception | None = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.fail_with is not None:
            raise self.fail_with
        self.embedded.extend(texts)
        return self._fake.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._fake.embed_query(text)


@pytest.fixture
def spy_embeddings() -> SpyEmbeddings:
    return SpyEmbeddings()


@pytest.fixture
def ingestion(
    clinic: ClinicFixture, report_storage: FakeReportStorage, spy_embeddings: SpyEmbeddings
) -> "Ingestion":
    return Ingestion(
        clinic,
        IngestionDeps(
            embeddings=spy_embeddings,
            model=TEST_EMBEDDING_MODEL,
            storage=report_storage,
            settings=get_settings(),
        ),
    )


@dataclass
class Ingestion:
    """Runs this clinic's pending ingestion jobs with fake embeddings."""

    clinic: ClinicFixture
    deps: IngestionDeps

    async def run(self) -> int:
        return await run_pending(self.clinic.sessionmaker, self.deps, clinic_id=self.clinic.id)


@pytest.fixture
def rag(
    app: FastAPI,
    sessionmaker: async_sessionmaker[AsyncSession],
    ingestion: "Ingestion",
) -> RagProviders:
    """Fake chat model + the ingestion test embeddings, wired into the chat endpoint."""
    providers = RagProviders(
        chat=FakeRecordsChatModel(),
        rewriter=FakeRecordsChatModel(),
        embeddings=ingestion.deps.embeddings,
        embedding_model=TEST_EMBEDDING_MODEL,
        chat_model="pytest-fake-chat",
    )
    app.dependency_overrides[rag_providers] = lambda: providers
    app.dependency_overrides[get_session_factory] = lambda: sessionmaker
    reset_chat_limits()
    return providers


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    """[(event, data), ...] from a text/event-stream body."""
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines.get("data", "{}"))))
    return events


def auth(user_id: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {user_id}"}


@pytest.fixture
async def wa(
    app: FastAPI, client: AsyncClient, clinic: ClinicFixture, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator["WhatsAppHarness"]:
    """WhatsApp wired to this clinic: signed webhooks in, a FakeWhatsApp out (no Meta calls)."""
    from pydantic import SecretStr  # noqa: PLC0415

    from app.deps import get_dispatch_deps  # noqa: PLC0415
    from app.services.whatsapp.client import FakeWhatsApp  # noqa: PLC0415
    from tests.whatsapp_utils import (  # noqa: PLC0415
        PHONE_ID,
        SECRET,
        VERIFY,
        WhatsAppHarness,
        bot_deps,
    )

    settings = get_settings()
    monkeypatch.setattr(settings, "whatsapp_app_secret", SecretStr(SECRET))
    monkeypatch.setattr(settings, "whatsapp_verify_token", SecretStr(VERIFY))
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", PHONE_ID)
    monkeypatch.setattr(settings, "inbound_clinic_id", clinic.id)
    fake = FakeWhatsApp()
    harness = WhatsAppHarness(client=client, clinic=clinic, fake=fake, deps=bot_deps(fake))
    app.dependency_overrides[get_dispatch_deps] = lambda: harness.deps.dispatch
    yield harness
