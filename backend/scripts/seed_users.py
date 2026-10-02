"""Create seeded staff auth users + profiles and link doctor logins.

Run AFTER supabase/seed.sql has been applied (it creates the clinic and doctors):

    cd backend
    uv run python -m scripts.seed_users

Idempotent: existing auth users (matched by email) are reused and profiles upserted.
Dev only. The password comes from SEED_PASSWORD (default Clinic@12345).
"""

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from supabase import Client, create_client

from app.core.config import get_settings
from app.db.session import dispose_engine, get_sessionmaker

CLINIC_ID = "11111111-1111-4111-8111-111111111111"


@dataclass(frozen=True)
class SeedUser:
    email: str
    full_name: str
    role: str
    phone: str
    doctor_id: str | None = None


SEED_USERS: list[SeedUser] = [
    SeedUser("admin@mediflow.test", "Neha Kapoor", "admin", "+919000000001"),
    SeedUser("reception1@mediflow.test", "Ramesh Babu", "receptionist", "+919000000002"),
    SeedUser("reception2@mediflow.test", "Anjali Rao", "receptionist", "+919000000003"),
    SeedUser(
        "dr.sharma@mediflow.test",
        "Dr. Anil Sharma",
        "doctor",
        "+919000000011",
        "d0c00000-0000-4000-8000-000000000001",
    ),
    SeedUser(
        "dr.iyer@mediflow.test",
        "Dr. Lakshmi Iyer",
        "doctor",
        "+919000000012",
        "d0c00000-0000-4000-8000-000000000002",
    ),
    SeedUser(
        "dr.khan@mediflow.test",
        "Dr. Imran Khan",
        "doctor",
        "+919000000013",
        "d0c00000-0000-4000-8000-000000000003",
    ),
]


def _existing_users_by_email(client: Client) -> dict[str, str]:
    found: dict[str, str] = {}
    page = 1
    while True:
        users: list[Any] = client.auth.admin.list_users(page=page, per_page=200)
        if not users:
            return found
        for user in users:
            if user.email:
                found[user.email.lower()] = str(user.id)
        page += 1


def _ensure_auth_user(client: Client, existing: dict[str, str], user: SeedUser, pw: str) -> str:
    if user.email in existing:
        return existing[user.email]
    response = client.auth.admin.create_user(
        {"email": user.email, "password": pw, "email_confirm": True}
    )
    return str(response.user.id)


async def main() -> None:
    settings = get_settings()
    password = os.environ.get("SEED_PASSWORD", "Clinic@12345")
    client = create_client(
        settings.supabase_url, settings.supabase_service_role_key.get_secret_value()
    )
    existing = _existing_users_by_email(client)

    async with get_sessionmaker()() as session, session.begin():
        clinic = await session.scalar(
            text("select id from public.clinics where id = :id"), {"id": CLINIC_ID}
        )
        if clinic is None:
            raise SystemExit("Clinic not found. Run supabase/seed.sql first.")

        for user in SEED_USERS:
            user_id = _ensure_auth_user(client, existing, user, password)
            await session.execute(
                text(
                    """
                    insert into public.profiles (id, clinic_id, full_name, phone, role, is_active)
                    values (
                      :id, :clinic_id, :full_name, :phone, cast(:role as public.user_role), true
                    )
                    on conflict (id) do update
                      set full_name = excluded.full_name,
                          phone = excluded.phone,
                          role = excluded.role,
                          is_active = true
                    """
                ),
                {
                    "id": user_id,
                    "clinic_id": CLINIC_ID,
                    "full_name": user.full_name,
                    "phone": user.phone,
                    "role": user.role,
                },
            )
            if user.doctor_id:
                await session.execute(
                    text("update public.doctors set profile_id = :pid where id = :did"),
                    {"pid": user_id, "did": user.doctor_id},
                )
            print(f"seeded {user.role:<13} {user.email}")

    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
