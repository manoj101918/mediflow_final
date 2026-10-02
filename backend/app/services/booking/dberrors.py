"""Map Postgres constraint violations to booking error codes."""

from sqlalchemy.exc import DBAPIError

from app.services.booking.results import BookingErrorCode

EXCLUSION_VIOLATION = "23P01"
UNIQUE_VIOLATION = "23505"
# Raised by the finalized-consultation triggers (clinical_records migration).
RECORD_LOCKED = "MF001"

_UNIQUE_CONSTRAINT_CODES = {
    "appointments_external_ref_key": BookingErrorCode.ALREADY_EXISTS,
    # Only reachable if token assignment bypassed the advisory lock; treat as a lost race.
    "appointments_doctor_day_token_key": BookingErrorCode.SLOT_TAKEN,
    # Lab catalog codes are unique per clinic (tests) and per test (parameters).
    "lab_tests_clinic_code_key": BookingErrorCode.ALREADY_EXISTS,
    "lab_test_parameters_test_code_key": BookingErrorCode.ALREADY_EXISTS,
}


def _driver_error(exc: DBAPIError) -> BaseException | None:
    # SQLAlchemy's asyncpg adapter wraps the asyncpg exception as the DBAPI error's cause.
    orig = exc.orig
    return getattr(orig, "__cause__", None) or orig


def sqlstate(exc: DBAPIError) -> str | None:
    driver = _driver_error(exc)
    code = getattr(driver, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
    return str(code) if code else None


def constraint_name(exc: DBAPIError) -> str | None:
    name = getattr(_driver_error(exc), "constraint_name", None)
    return str(name) if name else None


def booking_error_for(exc: DBAPIError) -> BookingErrorCode | None:
    """The booking error a constraint violation represents, or None if it is unexpected."""
    state = sqlstate(exc)
    if state == EXCLUSION_VIOLATION:
        return BookingErrorCode.SLOT_TAKEN
    if state == UNIQUE_VIOLATION:
        return _UNIQUE_CONSTRAINT_CODES.get(constraint_name(exc) or "")
    if state == RECORD_LOCKED:
        return BookingErrorCode.RECORD_LOCKED
    return None
