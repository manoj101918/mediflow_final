"""Fixed clock for booking tests: a Monday far in the future so real 'now' never interferes."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
DAY = date(2030, 1, 7)  # Monday (weekday 0)
NEXT_DAY = date(2030, 1, 8)  # Tuesday
NOW = datetime(2030, 1, 7, 8, 0, tzinfo=IST)  # before the doctor's first shift


def ist(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=IST)
