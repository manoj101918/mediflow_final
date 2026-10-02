"""Translate service results into HTTP errors."""

from app.core.errors import AppError
from app.services.booking.results import BookingErrorCode, BookingResult

HTTP_STATUS: dict[BookingErrorCode, int] = {
    BookingErrorCode.SLOT_TAKEN: 409,
    BookingErrorCode.INVALID_TRANSITION: 409,
    BookingErrorCode.ALREADY_EXISTS: 409,
    BookingErrorCode.DOCTOR_ON_LEAVE: 422,
    BookingErrorCode.OUTSIDE_SCHEDULE: 422,
    BookingErrorCode.IN_PAST: 422,
    BookingErrorCode.VALIDATION: 422,
    BookingErrorCode.NOT_FOUND: 404,
    BookingErrorCode.FORBIDDEN: 403,
    BookingErrorCode.RECORD_LOCKED: 409,
    BookingErrorCode.FILE_TOO_LARGE: 413,
    BookingErrorCode.UNSUPPORTED_FILE_TYPE: 415,
}


def unwrap[T](result: BookingResult[T]) -> T:
    """The successful value, or an AppError carrying the service's code and message."""
    if result.code is None:
        return result.unwrap()
    raise AppError(HTTP_STATUS[result.code], result.code.value, result.message)


def not_found(what: str) -> AppError:
    return AppError(404, BookingErrorCode.NOT_FOUND.value, f"{what} not found.")
