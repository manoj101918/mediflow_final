from datetime import date, time
from itertools import pairwise
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import Name, ShortText, UtcDateTime


class ScheduleIn(BaseModel):
    weekday: int = Field(ge=0, le=6, description="0 = Monday ... 6 = Sunday")
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start_time >= self.end_time:
            raise ValueError("Shift end must be after its start.")
        return self


class ScheduleOut(ScheduleIn):
    id: UUID


class SchedulesReplace(BaseModel):
    schedules: list[ScheduleIn] = Field(max_length=50)

    @model_validator(mode="after")
    def _no_overlaps(self) -> Self:
        by_day: dict[int, list[ScheduleIn]] = {}
        for shift in self.schedules:
            by_day.setdefault(shift.weekday, []).append(shift)
        for shifts in by_day.values():
            shifts.sort(key=lambda s: s.start_time)
            for earlier, later in pairwise(shifts):
                if later.start_time < earlier.end_time:
                    raise ValueError("Shifts on the same day must not overlap.")
        return self


class LeaveIn(BaseModel):
    leave_date: date
    reason: ShortText = None


class LeaveOut(BaseModel):
    id: UUID
    leave_date: date
    reason: str | None


class LeaveCreatedOut(LeaveOut):
    # Live appointments already booked on that day; the front desk must move or cancel them.
    affected_appointments: int


class DoctorOut(BaseModel):
    id: UUID
    full_name: str
    specialization: str
    consultation_fee: float
    default_slot_minutes: int
    is_active: bool
    profile_id: UUID | None
    schedules: list[ScheduleOut]
    upcoming_leaves: list[LeaveOut]
    on_leave_today: bool
    created_at: UtcDateTime


class DoctorCreate(BaseModel):
    full_name: Name
    specialization: Name
    consultation_fee: float = Field(default=0, ge=0, le=1_000_000)
    default_slot_minutes: int = Field(default=15, ge=5, le=240)


class DoctorUpdate(BaseModel):
    full_name: Name | None = None
    specialization: Name | None = None
    consultation_fee: float | None = Field(default=None, ge=0, le=1_000_000)
    default_slot_minutes: int | None = Field(default=None, ge=5, le=240)
    is_active: bool | None = None


class SlotOut(BaseModel):
    starts_at: UtcDateTime
    ends_at: UtcDateTime


class DaySlotsOut(BaseModel):
    doctor_id: UUID
    date: date
    slot_minutes: int
    on_leave: bool
    slots: list[SlotOut]
