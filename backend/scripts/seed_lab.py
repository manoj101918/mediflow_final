"""Seed the in-house lab for the seed clinic (dev only).

Run after supabase/seed.sql, scripts.seed_users and scripts.seed_clinical:

    cd backend
    uv run python -m scripts.seed_lab

Idempotent: tests are matched by code and existing rows are kept.
"""

import asyncio
from uuid import UUID

from app.db.session import dispose_engine, get_sessionmaker
from app.services.labs.catalog_seed import install_catalog

CLINIC = UUID("11111111-1111-4111-8111-111111111111")


async def main() -> None:
    async with get_sessionmaker()() as session:
        added = await install_catalog(session, CLINIC)
        print(f"lab catalog: {added} test(s) added")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
