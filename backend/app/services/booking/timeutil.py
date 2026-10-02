"""Clinic-local time helpers. Datetimes are stored as UTC timestamptz; days are clinic-local."""

from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Asia/Kolkata"


@lru_cache
def clinic_tz(name: str = DEFAULT_TIMEZONE) -> ZoneInfo:
    return ZoneInfo(name)


def utcnow() -> datetime:
    return datetime.now(UTC)


def local_date(moment: datetime, tz: ZoneInfo) -> date:
    return moment.astimezone(tz).date()


def today_local(tz: ZoneInfo, now: datetime | None = None) -> date:
    return local_date(now or utcnow(), tz)


def local_datetime(day: date, at: time, tz: ZoneInfo) -> datetime:
    """Clinic-local wall time on `day` as an aware datetime."""
    return datetime.combine(day, at, tzinfo=tz)


def day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """[start, end) of a clinic-local day as aware datetimes."""
    start = local_datetime(day, time.min, tz)
    return start, local_datetime(day + timedelta(days=1), time.min, tz)
