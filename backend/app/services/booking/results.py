"""Typed results: business-rule failures are returned as values, never raised."""

import enum
from dataclasses import dataclass


class BookingErrorCode(enum.StrEnum):
    SLOT_TAKEN = "SLOT_TAKEN"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    DOCTOR_ON_LEAVE = "DOCTOR_ON_LEAVE"
    OUTSIDE_SCHEDULE = "OUTSIDE_SCHEDULE"
    IN_PAST = "IN_PAST"
    VALIDATION = "VALIDATION"
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"


@dataclass(frozen=True)
class BookingResult[T]:
    value: T | None = None
    code: BookingErrorCode | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.code is None

    def unwrap(self) -> T:
        """Return the value of a successful result (raises on failure)."""
        if self.code is not None or self.value is None:
            raise ValueError(f"unwrap() on failed result: {self.code}: {self.message}")
        return self.value


def success[T](value: T) -> BookingResult[T]:
    return BookingResult(value=value)


def failure[T](code: BookingErrorCode, message: str) -> BookingResult[T]:
    return BookingResult(code=code, message=message)
