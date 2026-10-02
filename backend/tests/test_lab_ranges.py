"""Reference range selection, flagging and status derivation (pure functions)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import Gender, LabFlag, LabItemStatus, LabOrderStatus, LabRangeSex, UserRole
from app.services.labs.ranges import (
    age_on,
    delta_exceeded,
    flag_numeric,
    flag_text,
    range_label,
    select_range,
)
from app.services.labs.transitions import LabAction, derive_order_status, role_allowed

D = Decimal


@dataclass(frozen=True)
class R:
    sex: LabRangeSex = LabRangeSex.ANY
    age_min_years: int | None = None
    age_max_years: int | None = None
    low: Decimal | None = None
    high: Decimal | None = None
    critical_low: Decimal | None = None
    critical_high: Decimal | None = None
    text_normal: str | None = None


ANY = R(low=D(1), high=D(10))
MALE = R(sex=LabRangeSex.MALE, low=D(13), high=D(17))
FEMALE = R(sex=LabRangeSex.FEMALE, low=D(12), high=D(15))
CHILD = R(age_min_years=0, age_max_years=12, low=D(11), high=D(14))
OLD_MALE = R(sex=LabRangeSex.MALE, age_min_years=60, low=D(12.5), high=D(16))


@pytest.mark.parametrize(
    ("gender", "age", "expected"),
    [
        (Gender.MALE, 40, MALE),
        (Gender.FEMALE, 40, FEMALE),
        (Gender.MALE, 70, OLD_MALE),  # sex + age band beats sex only
        (Gender.MALE, 8, MALE),  # sex-specific beats an any-sex child band
        (Gender.OTHER, 8, CHILD),
        (Gender.OTHER, 40, ANY),
        (None, None, ANY),  # unknown age: banded ranges don't apply
    ],
)
def test_select_range(gender: Gender | None, age: int | None, expected: R) -> None:
    assert select_range([ANY, MALE, FEMALE, CHILD, OLD_MALE], gender, age) is expected


def test_no_applicable_range() -> None:
    assert select_range([MALE], Gender.FEMALE, 30) is None
    assert select_range([], Gender.MALE, 30) is None


def test_age_on_birthday_boundary() -> None:
    dob = date(1970, 6, 15)
    assert age_on(date(2026, 6, 14), dob, None) == 55
    assert age_on(date(2026, 6, 15), dob, None) == 56
    assert age_on(date(2026, 6, 15), None, 42) == 42


POTASSIUM = R(low=D("3.5"), high=D("5.1"), critical_low=D("2.8"), critical_high=D("6.2"))


@pytest.mark.parametrize(
    ("value", "flag"),
    [
        ("2.7", LabFlag.CRITICAL_LOW),
        ("2.8", LabFlag.CRITICAL_LOW),  # critical limits are inclusive
        ("3.4", LabFlag.LOW),
        ("3.5", LabFlag.NORMAL),
        ("5.1", LabFlag.NORMAL),
        ("5.2", LabFlag.HIGH),
        ("6.2", LabFlag.CRITICAL_HIGH),
    ],
)
def test_flag_numeric(value: str, flag: LabFlag) -> None:
    assert flag_numeric(D(value), POTASSIUM) == flag


def test_flag_one_sided_and_missing_ranges() -> None:
    ldl = R(high=D(100))
    assert flag_numeric(D(118), ldl) == LabFlag.HIGH
    assert flag_numeric(D(80), ldl) == LabFlag.NORMAL
    assert flag_numeric(D(80), None) is None
    assert flag_numeric(D(80), R()) is None


def test_flag_text() -> None:
    negative = R(text_normal="Negative")
    assert flag_text("negative", negative) == LabFlag.NORMAL
    assert flag_text("Positive", negative) == LabFlag.ABNORMAL
    assert flag_text("Yellow", R()) is None


def test_range_labels() -> None:
    assert range_label(R(low=D("4.0"), high=D("5.6"))) == "4.0 - 5.6"
    assert range_label(R(high=D(200))) == "< 200"
    assert range_label(R(low=D(40))) == "> 40"
    assert range_label(R(text_normal="Negative")) == "Negative"
    assert range_label(None) is None


def test_delta() -> None:
    assert delta_exceeded(D("8.1"), D("6.9"), D(20)) is False
    assert delta_exceeded(D("8.1"), D("5.0"), D(20)) is True
    assert delta_exceeded(D("8.1"), D("5.0"), None) is False


S = LabItemStatus


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([S.ORDERED, S.ORDERED], LabOrderStatus.ORDERED),
        ([S.ORDERED, S.SAMPLE_COLLECTED], LabOrderStatus.IN_PROGRESS),
        ([S.RELEASED, S.RESULT_ENTERED], LabOrderStatus.PARTIALLY_RELEASED),
        ([S.RELEASED, S.CANCELLED], LabOrderStatus.RELEASED),
        ([S.CANCELLED, S.CANCELLED], LabOrderStatus.CANCELLED),
        ([S.SAMPLE_REJECTED], LabOrderStatus.IN_PROGRESS),
    ],
)
def test_derive_order_status(statuses: list[LabItemStatus], expected: LabOrderStatus) -> None:
    assert derive_order_status(statuses) == expected


TECH, HEAD = UserRole.LAB_TECHNICIAN, UserRole.LAB_SUPERVISOR


@pytest.mark.parametrize(
    ("action", "role", "verification", "allowed"),
    [
        (LabAction.SUBMIT, TECH, True, True),
        (LabAction.VERIFY, TECH, True, False),
        (LabAction.SEND_BACK, TECH, True, False),
        (LabAction.RELEASE, TECH, True, False),
        (LabAction.RELEASE, TECH, False, True),
        (LabAction.AMEND, TECH, True, False),
        (LabAction.AMEND, TECH, False, True),
        (LabAction.VERIFY, HEAD, True, True),
        (LabAction.RELEASE, HEAD, True, True),
        (LabAction.COLLECT, UserRole.DOCTOR, False, False),
        (LabAction.COLLECT, UserRole.RECEPTIONIST, False, False),
    ],
)
def test_role_allowed(action: LabAction, role: UserRole, verification: bool, allowed: bool) -> None:
    assert role_allowed(action, role, verification) is allowed
