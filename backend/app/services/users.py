"""Staff accounts: Supabase Auth user + profile (+ optional doctor link)."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol
from uuid import UUID

from anyio import to_thread
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from supabase import Client, create_client
from supabase_auth.errors import AuthApiError

from app.core.config import get_settings
from app.db.models import Doctor, Profile, UserRole
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success


class EmailTakenError(Exception):
    pass


class AuthAdmin(Protocol):
    """Creates and removes Supabase Auth users (blocking calls)."""

    def create_user(self, email: str, password: str) -> UUID: ...

    def delete_user(self, user_id: UUID) -> None: ...


class SupabaseAuthAdmin:
    def __init__(self, client: Client) -> None:
        self._client = client

    def create_user(self, email: str, password: str) -> UUID:
        try:
            response = self._client.auth.admin.create_user(
                {"email": email, "password": password, "email_confirm": True}
            )
        except AuthApiError as exc:
            if exc.code == "email_exists" or exc.status == 422:
                raise EmailTakenError(email) from exc
            raise
        return UUID(str(response.user.id))

    def delete_user(self, user_id: UUID) -> None:
        self._client.auth.admin.delete_user(str(user_id))


@lru_cache
def get_auth_admin() -> AuthAdmin:
    settings = get_settings()
    return SupabaseAuthAdmin(
        create_client(settings.supabase_url, settings.supabase_service_role_key.get_secret_value())
    )


@dataclass(frozen=True)
class StaffUser:
    profile: Profile
    email: str | None
    doctor_id: UUID | None


_EMAILS = text("select id, email from auth.users where id = any(:ids)")


async def _emails(session: AsyncSession, ids: list[UUID]) -> dict[UUID, str | None]:
    if not ids:
        return {}
    rows = await session.execute(_EMAILS, {"ids": ids})
    return {UUID(str(row[0])): (str(row[1]) if row[1] else None) for row in rows}


async def list_users(session: AsyncSession, clinic_id: UUID) -> list[StaffUser]:
    rows = list(
        await session.execute(
            select(Profile, Doctor.id)
            .outerjoin(Doctor, Doctor.profile_id == Profile.id)
            .where(Profile.clinic_id == clinic_id)
            .order_by(Profile.role, Profile.full_name)
        )
    )
    emails = await _emails(session, [profile.id for profile, _ in rows])
    return [StaffUser(p, emails.get(p.id), doctor_id) for p, doctor_id in rows]


async def get_user(session: AsyncSession, clinic_id: UUID, user_id: UUID) -> StaffUser | None:
    row = (
        await session.execute(
            select(Profile, Doctor.id)
            .outerjoin(Doctor, Doctor.profile_id == Profile.id)
            .where(Profile.id == user_id, Profile.clinic_id == clinic_id)
        )
    ).first()
    if row is None:
        return None
    profile, doctor_id = row
    return StaffUser(profile, (await _emails(session, [profile.id])).get(profile.id), doctor_id)


async def create_user(
    session: AsyncSession,
    auth_admin: AuthAdmin,
    clinic_id: UUID,
    *,
    email: str,
    password: str,
    full_name: str,
    phone: str | None,
    role: UserRole,
    doctor_id: UUID | None,
) -> BookingResult[StaffUser]:
    if doctor_id is not None:
        doctor = await session.scalar(
            select(Doctor).where(Doctor.id == doctor_id, Doctor.clinic_id == clinic_id)
        )
        if doctor is None:
            return failure(BookingErrorCode.NOT_FOUND, "Doctor not found.")
        if doctor.profile_id is not None:
            return failure(BookingErrorCode.ALREADY_EXISTS, "That doctor already has a login.")

    # The Auth API is a separate system: create the login first, undo it if the profile fails.
    try:
        user_id = await to_thread.run_sync(auth_admin.create_user, email, password)
    except EmailTakenError:
        return failure(BookingErrorCode.ALREADY_EXISTS, "An account with that email exists.")
    try:
        profile = Profile(
            id=user_id, clinic_id=clinic_id, full_name=full_name, phone=phone, role=role
        )
        session.add(profile)
        await session.flush()
        if doctor_id is not None:
            await session.execute(
                update(Doctor).where(Doctor.id == doctor_id).values(profile_id=user_id)
            )
        await session.commit()
    except Exception:
        await session.rollback()
        await to_thread.run_sync(auth_admin.delete_user, user_id)
        raise
    return success(StaffUser(profile, email, doctor_id))


async def update_user(
    session: AsyncSession, clinic_id: UUID, user_id: UUID, changes: dict[str, Any]
) -> BookingResult[StaffUser]:
    profile = await session.scalar(
        select(Profile).where(Profile.id == user_id, Profile.clinic_id == clinic_id)
    )
    if profile is None:
        return failure(BookingErrorCode.NOT_FOUND, "User not found.")
    if "full_name" in changes and changes["full_name"] is None:
        return failure(BookingErrorCode.VALIDATION, "Name is required.")
    for name, value in changes.items():
        setattr(profile, name, value)
    await session.commit()
    user = await get_user(session, clinic_id, user_id)
    assert user is not None  # noqa: S101 - just updated
    return success(user)
