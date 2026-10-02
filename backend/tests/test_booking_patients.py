import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.booking import BookingErrorCode, find_or_create_patient, normalize_phone
from tests.conftest import ClinicFixture

Sessions = async_sessionmaker[AsyncSession]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9848012345", "+919848012345"),
        ("98480 12345", "+919848012345"),
        ("098480-12345", "+919848012345"),
        ("+91 98480 12345", "+919848012345"),
        ("+1 415 555 2671", "+14155552671"),
        ("12345", None),
        ("not a phone", None),
    ],
)
def test_normalize_phone(raw: str, expected: str | None) -> None:
    assert normalize_phone(raw) == expected


async def test_reuses_patient_with_same_phone_and_similar_name(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    existing = await clinic.add_patient("Ravi Kumar", "+919848012345")
    async with sessionmaker() as session:
        for name in ("ravi kumar", "Ravi  Kumarr", "RAVI KUMAR"):
            match = (await find_or_create_patient(session, clinic.id, "98480 12345", name)).unwrap()
            assert match.created is False
            assert match.patient.id == existing


async def test_family_member_on_shared_phone_is_new_patient(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    existing = await clinic.add_patient("Ravi Kumar", "+919848012345")
    async with sessionmaker() as session:
        match = (
            await find_or_create_patient(session, clinic.id, "9848012345", "Sunita Kumar")
        ).unwrap()
        await session.commit()
    assert match.created is True
    assert match.patient.id != existing
    assert match.patient.phone == "+919848012345"
    assert match.patient.full_name == "Sunita Kumar"


async def test_same_name_different_phone_is_new_patient(
    sessionmaker: Sessions, clinic: ClinicFixture
) -> None:
    await clinic.add_patient("Ravi Kumar", "+919848012345")
    async with sessionmaker() as session:
        match = (
            await find_or_create_patient(session, clinic.id, "9000000001", "Ravi Kumar")
        ).unwrap()
        await session.rollback()
    assert match.created is True


async def test_invalid_input(sessionmaker: Sessions, clinic: ClinicFixture) -> None:
    async with sessionmaker() as session:
        bad_phone = await find_or_create_patient(session, clinic.id, "123", "Ravi")
        no_name = await find_or_create_patient(session, clinic.id, "9848012345", "   ")
    assert bad_phone.code is BookingErrorCode.VALIDATION
    assert no_name.code is BookingErrorCode.VALIDATION
