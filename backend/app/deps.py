"""FastAPI dependencies: DB session, authenticated staff user, role guards."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import InvalidTokenError, JWTVerifier, get_jwt_verifier
from app.db.models import Clinic, Doctor, Profile, UserRole
from app.db.session import get_session

DbSession = Annotated[AsyncSession, Depends(get_session)]

logger = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)
_UNAUTHENTICATED = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str | None
    full_name: str
    role: UserRole
    clinic_id: UUID
    clinic_name: str
    clinic_timezone: str
    # Set only for doctors whose profile is linked to a doctors row.
    doctor_id: UUID | None


async def get_current_user(
    session: DbSession,
    verifier: Annotated[JWTVerifier, Depends(get_jwt_verifier)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "UNAUTHENTICATED",
            "Sign in to continue.",
            headers=_UNAUTHENTICATED,
        )
    try:
        claims = await run_in_threadpool(verifier.verify, credentials.credentials)
    except InvalidTokenError as exc:
        # Reason type only (e.g. ExpiredSignatureError); never log the token itself.
        logger.info("auth_rejected", reason=type(exc.__cause__ or exc).__name__)
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "INVALID_TOKEN",
            "Your session has expired. Sign in again.",
            headers=_UNAUTHENTICATED,
        ) from exc

    row = (
        await session.execute(
            select(Profile, Clinic, Doctor.id)
            .join(Clinic, Clinic.id == Profile.clinic_id)
            .outerjoin(Doctor, Doctor.profile_id == Profile.id)
            .where(Profile.id == claims.user_id)
        )
    ).one_or_none()
    if row is None:
        raise AppError(status.HTTP_403_FORBIDDEN, "NO_PROFILE", "No staff profile for this login.")
    profile, clinic, doctor_id = row
    if not profile.is_active:
        raise AppError(
            status.HTTP_403_FORBIDDEN, "ACCOUNT_INACTIVE", "This account has been deactivated."
        )
    return CurrentUser(
        id=profile.id,
        email=claims.email,
        full_name=profile.full_name,
        role=profile.role,
        clinic_id=clinic.id,
        clinic_name=clinic.name,
        clinic_timezone=clinic.timezone,
        doctor_id=doctor_id if profile.role == UserRole.DOCTOR else None,
    )


AuthUser = Annotated[CurrentUser, Depends(get_current_user)]


def require_role(*roles: UserRole) -> Callable[[CurrentUser], Awaitable[CurrentUser]]:
    allowed = frozenset(roles)

    async def _guard(user: AuthUser) -> CurrentUser:
        if user.role not in allowed:
            raise AppError(
                status.HTTP_403_FORBIDDEN, "FORBIDDEN", "You do not have access to this action."
            )
        return user

    return _guard
