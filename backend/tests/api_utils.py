"""Helpers for API tests, which run against the real clock: book tomorrow (IST) to stay future."""

from datetime import date, datetime, time, timedelta

from app.services.booking.timeutil import clinic_tz, today_local

IST = clinic_tz()
TODAY = today_local(IST)
TOMORROW = TODAY + timedelta(days=1)
EVERY_DAY = (0, 1, 2, 3, 4, 5, 6)


def at(hour: int, minute: int = 0, day: date = TOMORROW) -> str:
    """ISO timestamp with the +05:30 offset, as the frontend sends it."""
    return datetime.combine(day, time(hour, minute), tzinfo=IST).isoformat()
