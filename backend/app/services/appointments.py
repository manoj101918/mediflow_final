"""Read-side appointment queries (lists, summary, detail). Writes go through services.booking."""

from collections import Counter
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appointment,
    AppointmentEvent,
    AppointmentSource,
    AppointmentStatus,
    Doctor,
    Patient,
    Profile,
)

AppointmentRow = tuple[Appointment, Patient, Doctor]


@dataclass(frozen=True)
class AppointmentFilters:
    date_from: date
    date_to: date
    # Doctors are always restricted to their own doctor_id by the caller.
    doctor_id: UUID | None = None
    statuses: tuple[AppointmentStatus, ...] = ()
    source: AppointmentSource | None = None
    query: str | None = None


def _base(clinic_id: UUID) -> Select[Appointment, Patient, Doctor]:
    return (
        select(Appointment, Patient, Doctor)
        .join(Patient, Patient.id == Appointment.patient_id)
        .join(Doctor, Doctor.id == Appointment.doctor_id)
        .where(Appointment.clinic_id == clinic_id)
    )


async def list_appointments(
    session: AsyncSession,
    clinic_id: UUID,
    filters: AppointmentFilters,
    page: int,
    page_size: int,
) -> tuple[list[AppointmentRow], int]:
    stmt = _base(clinic_id).where(
        Appointment.appointment_date >= filters.date_from,
        Appointment.appointment_date <= filters.date_to,
    )
    if filters.doctor_id is not None:
        stmt = stmt.where(Appointment.doctor_id == filters.doctor_id)
    if filters.statuses:
        stmt = stmt.where(Appointment.status.in_(filters.statuses))
    if filters.source is not None:
        stmt = stmt.where(Appointment.source == filters.source)
    if filters.query and (q := filters.query.strip()):
        digits = "".join(ch for ch in q if ch.isdigit())
        conditions = [Patient.full_name.icontains(q, autoescape=True)]
        if len(digits) >= 3:
            conditions.append(Patient.phone.contains(digits))
        if q.isdigit():
            conditions.append(Appointment.token_number == int(q))
        stmt = stmt.where(or_(*conditions))

    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await session.execute(
        stmt.order_by(Appointment.appointment_date, Appointment.starts_at, Appointment.token_number)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return [(a, p, d) for a, p, d in rows], total


@dataclass(frozen=True)
class Summary:
    total: int
    by_status: dict[AppointmentStatus, int]
    by_source: dict[AppointmentSource, int]


async def day_summary(
    session: AsyncSession, clinic_id: UUID, day: date, doctor_id: UUID | None
) -> Summary:
    stmt = select(Appointment.status, Appointment.source).where(
        Appointment.clinic_id == clinic_id, Appointment.appointment_date == day
    )
    if doctor_id is not None:
        stmt = stmt.where(Appointment.doctor_id == doctor_id)
    rows = list(await session.execute(stmt))
    statuses = Counter(status for status, _ in rows)
    sources = Counter(source for _, source in rows)
    return Summary(
        total=len(rows),
        by_status={status: statuses.get(status, 0) for status in AppointmentStatus},
        by_source={source: sources.get(source, 0) for source in AppointmentSource},
    )


async def get_appointment(
    session: AsyncSession, clinic_id: UUID, appointment_id: UUID
) -> AppointmentRow | None:
    row = (await session.execute(_base(clinic_id).where(Appointment.id == appointment_id))).first()
    if row is None:
        return None
    appointment, patient, doctor = row
    return appointment, patient, doctor


async def get_appointment_row(
    session: AsyncSession, clinic_id: UUID, appointment: Appointment
) -> AppointmentRow:
    """Patient and doctor for an appointment that was just written."""
    row = await get_appointment(session, clinic_id, appointment.id)
    assert row is not None  # noqa: S101 - the caller just committed this appointment
    return row


async def appointment_events(
    session: AsyncSession, appointment_id: UUID
) -> list[tuple[AppointmentEvent, str | None]]:
    rows = await session.execute(
        select(AppointmentEvent, Profile.full_name)
        .outerjoin(Profile, Profile.id == AppointmentEvent.changed_by)
        .where(AppointmentEvent.appointment_id == appointment_id)
        .order_by(AppointmentEvent.created_at, AppointmentEvent.id)
    )
    return [(event, name) for event, name in rows]
