from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.results import unwrap
from app.db.models import UserRole
from app.deps import AuthUser, DbSession, clinic_today
from app.schemas.doctors import DaySlotsOut, DoctorOut, LeaveOut, ScheduleOut, SlotOut
from app.services import doctors as service
from app.services.booking import get_available_slots

router = APIRouter(prefix="/doctors", tags=["doctors"])


def to_out(item: service.DoctorWithCalendar, today: date) -> DoctorOut:
    doctor = item.doctor
    return DoctorOut(
        id=doctor.id,
        full_name=doctor.full_name,
        specialization=doctor.specialization,
        consultation_fee=float(doctor.consultation_fee),
        default_slot_minutes=doctor.default_slot_minutes,
        is_active=doctor.is_active,
        profile_id=doctor.profile_id,
        schedules=[
            ScheduleOut(id=s.id, weekday=s.weekday, start_time=s.start_time, end_time=s.end_time)
            for s in item.schedules
        ],
        upcoming_leaves=[
            LeaveOut(id=leave.id, leave_date=leave.leave_date, reason=leave.reason)
            for leave in item.upcoming_leaves
        ],
        on_leave_today=any(leave.leave_date == today for leave in item.upcoming_leaves),
        created_at=doctor.created_at,
    )


@router.get("")
async def list_doctors(
    session: DbSession, user: AuthUser, include_inactive: bool = False
) -> list[DoctorOut]:
    """Doctors with weekly schedules and leave for the next 60 days (inactive: admin only)."""
    today = clinic_today(user)
    items = await service.list_doctors(
        session,
        user.clinic_id,
        today,
        include_inactive=include_inactive and user.role == UserRole.ADMIN,
    )
    return [to_out(item, today) for item in items]


@router.get("/{doctor_id}/slots")
async def doctor_slots(
    doctor_id: UUID,
    session: DbSession,
    user: AuthUser,
    on: Annotated[date | None, Query(alias="date")] = None,
) -> DaySlotsOut:
    """Free slots for one clinic-local day (default today; past slots are omitted)."""
    day_slots = unwrap(
        await get_available_slots(session, user.clinic_id, doctor_id, on or clinic_today(user))
    )
    return DaySlotsOut(
        doctor_id=day_slots.doctor_id,
        date=day_slots.date,
        slot_minutes=day_slots.slot_minutes,
        on_leave=day_slots.on_leave,
        slots=[SlotOut(starts_at=s.starts_at, ends_at=s.ends_at) for s in day_slots.slots],
    )
