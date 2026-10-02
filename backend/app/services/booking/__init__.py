"""Channel-agnostic booking service.

Every channel (reception dashboard, WhatsApp, voice) books through these functions, so the
rules live in one place. Nothing here imports FastAPI or knows about HTTP.
"""

from app.services.booking.actor import Actor, StaffActor, SystemActor
from app.services.booking.create import NewAppointment, create_appointment, reschedule_appointment
from app.services.booking.patients import PatientMatch, find_or_create_patient, normalize_phone
from app.services.booking.results import BookingErrorCode, BookingResult
from app.services.booking.slots import DaySlots, Slot, get_available_slots
from app.services.booking.status import (
    ALLOWED_TRANSITIONS,
    approve_appointment,
    can_transition,
    reject_appointment,
    update_appointment_status,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "Actor",
    "BookingErrorCode",
    "BookingResult",
    "DaySlots",
    "NewAppointment",
    "PatientMatch",
    "Slot",
    "StaffActor",
    "SystemActor",
    "approve_appointment",
    "can_transition",
    "create_appointment",
    "find_or_create_patient",
    "get_available_slots",
    "normalize_phone",
    "reject_appointment",
    "reschedule_appointment",
    "update_appointment_status",
]
