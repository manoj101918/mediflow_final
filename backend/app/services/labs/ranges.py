"""Reference range selection and result flagging (pure functions).

The range for a result is chosen by the patient's sex and age at sample collection:
an age-banded range that fits beats an open one (a child's band wins over adult ranges),
then a sex-specific range beats an 'any' range, and among age bands the narrowest wins.
Critical limits are inclusive (value <= critical_low or value >= critical_high); normal
limits are inclusive too (low <= value <= high).
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.db.models import Gender, LabFlag, LabRangeSex

CRITICAL_FLAGS = frozenset({LabFlag.CRITICAL_LOW, LabFlag.CRITICAL_HIGH})
ABNORMAL_FLAGS = frozenset(
    {LabFlag.LOW, LabFlag.HIGH, LabFlag.CRITICAL_LOW, LabFlag.CRITICAL_HIGH, LabFlag.ABNORMAL}
)


class RangeLike(Protocol):
    @property
    def sex(self) -> LabRangeSex: ...
    @property
    def age_min_years(self) -> int | None: ...
    @property
    def age_max_years(self) -> int | None: ...
    @property
    def low(self) -> Decimal | None: ...
    @property
    def high(self) -> Decimal | None: ...
    @property
    def critical_low(self) -> Decimal | None: ...
    @property
    def critical_high(self) -> Decimal | None: ...
    @property
    def text_normal(self) -> str | None: ...


def age_on(day: date, date_of_birth: date | None, age_years: int | None) -> int | None:
    """Whole years on `day`; falls back to the recorded age when there is no date of birth."""
    if date_of_birth is None:
        return age_years
    years = day.year - date_of_birth.year
    if (day.month, day.day) < (date_of_birth.month, date_of_birth.day):
        years -= 1
    return max(years, 0)


def _range_sex(gender: Gender | None) -> LabRangeSex | None:
    if gender == Gender.MALE:
        return LabRangeSex.MALE
    if gender == Gender.FEMALE:
        return LabRangeSex.FEMALE
    return None


def select_range[R: RangeLike](
    ranges: Sequence[R], gender: Gender | None, age: int | None
) -> R | None:
    """The most specific range that applies to this patient, or None."""
    sex = _range_sex(gender)
    best: tuple[tuple[int, int, int], R] | None = None
    for r in ranges:
        if r.sex not in (LabRangeSex.ANY, sex):
            continue
        banded = r.age_min_years is not None or r.age_max_years is not None
        if banded:
            if age is None:
                continue
            if r.age_min_years is not None and age < r.age_min_years:
                continue
            if r.age_max_years is not None and age > r.age_max_years:
                continue
        width = (r.age_max_years if r.age_max_years is not None else 150) - (r.age_min_years or 0)
        # Higher is better: age-banded, then sex-specific, then narrower band.
        score = (int(banded), int(r.sex != LabRangeSex.ANY), -width)
        if best is None or score > best[0]:
            best = (score, r)
    return best[1] if best else None


def flag_numeric(value: Decimal, r: RangeLike | None) -> LabFlag | None:
    if r is None:
        return None
    if r.critical_low is not None and value <= r.critical_low:
        return LabFlag.CRITICAL_LOW
    if r.critical_high is not None and value >= r.critical_high:
        return LabFlag.CRITICAL_HIGH
    if r.low is not None and value < r.low:
        return LabFlag.LOW
    if r.high is not None and value > r.high:
        return LabFlag.HIGH
    if r.low is None and r.high is None:
        return None
    return LabFlag.NORMAL


def flag_text(value: str, r: RangeLike | None) -> LabFlag | None:
    if r is None or not r.text_normal:
        return None
    same = value.strip().casefold() == r.text_normal.strip().casefold()
    return LabFlag.NORMAL if same else LabFlag.ABNORMAL


def format_number(value: Decimal, decimals: int | None = None) -> str:
    if decimals is not None:
        return f"{value:.{decimals}f}"
    # As stored/entered: "4.0" stays "4.0", "200" stays "200".
    return format(value, "f")


def range_label(r: RangeLike | None) -> str | None:
    """How the range reads on a report: '4.0 - 5.6', '< 200', '> 40' or 'Negative'."""
    if r is None:
        return None
    if r.low is not None and r.high is not None:
        return f"{format_number(r.low)} - {format_number(r.high)}"
    if r.high is not None:
        return f"< {format_number(r.high)}"
    if r.low is not None:
        return f"> {format_number(r.low)}"
    return r.text_normal


def delta_exceeded(previous: Decimal, current: Decimal, percent: Decimal | None) -> bool:
    """True when the change from the previous value is larger than `percent` of it."""
    if percent is None:
        return False
    if previous == 0:
        return current != 0
    return abs(current - previous) / abs(previous) * 100 > percent
