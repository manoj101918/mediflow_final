from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.results import not_found, unwrap
from app.core.errors import AppError
from app.db.models import AppointmentSource, AppointmentStatus, UserRole
from app.deps import AuthUser, CurrentUser, DbSession, FrontDeskUser, clinic_today, staff_actor
from app.schemas.appointments import (
    AppointmentCreate,
    AppointmentDetailOut,
    AppointmentEventOut,
    AppointmentOut,
    AppointmentSummaryOut,
    DoctorBrief,
    PatientBrief,
    RejectIn,
    RescheduleIn,
    StatusUpdate,
)
from app.schemas.common import Page
from app.services import appointments as queries
from app.services.booking import (
    NewAppointment,
    approve_appointment,
    create_appointment,
    reject_appointment,
    reschedule_appointment,
    update_appointment_status,
)
from app.services.patients import patient_age
from app.services.records.consultations import complete_visit

router = APIRouter(prefix="/appointments", tags=["appointments"])

MAX_RANGE_DAYS = 62


def to_out(row: queries.AppointmentRow, user: CurrentUser) -> AppointmentOut:
    appointment, patient, doctor = row
    return AppointmentOut(
        id=appointment.id,
        token_number=appointment.token_number,
        status=appointment.status,
        source=appointment.source,
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        appointment_date=appointment.appointment_date,
        reason_for_visit=appointment.reason_for_visit,
        notes=appointment.notes,
        external_ref=appointment.external_ref,
        created_at=appointment.created_at,
        updated_at=appointment.updated_at,
        patient=PatientBrief(
            id=patient.id,
            full_name=patient.full_name,
            phone=None if user.role == UserRole.DOCTOR else patient.phone,
            gender=patient.gender,
            age=patient_age(patient, clinic_today(user)),
        ),
        doctor=DoctorBrief(
            id=doctor.id, full_name=doctor.full_name, specialization=doctor.specialization
        ),
    )


def _own_doctor_scope(user: CurrentUser, doctor_id: UUID | None) -> UUID | None:
    """Doctors only ever see their own appointments, whatever they ask for."""
    if user.role != UserRole.DOCTOR:
        return doctor_id
    if user.doctor_id is None:
        raise AppError(403, "FORBIDDEN", "Your login is not linked to a doctor.")
    return user.doctor_id


@router.get("")
async def list_appointments(
    session: DbSession,
    user: AuthUser,
    on: Annotated[date | None, Query(alias="date")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    doctor_id: UUID | None = None,
    status_filter: Annotated[list[AppointmentStatus], Query(alias="status")] = [],  # noqa: B006
    source: AppointmentSource | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
) -> Page[AppointmentOut]:
    """Appointments for one day (`date`, default today) or a `date_from`..`date_to` range."""
    today = clinic_today(user)
    start = date_from or on or today
    end = date_to or on or start
    if end < start:
        raise AppError(422, "VALIDATION", "date_to must not be before date_from.")
    if end - start > timedelta(days=MAX_RANGE_DAYS):
        raise AppError(422, "VALIDATION", f"Choose a range of at most {MAX_RANGE_DAYS} days.")

    filters = queries.AppointmentFilters(
        date_from=start,
        date_to=end,
        doctor_id=_own_doctor_scope(user, doctor_id),
        statuses=tuple(status_filter),
        source=source,
        query=q,
    )
    rows, total = await queries.list_appointments(session, user.clinic_id, filters, page, page_size)
    return Page(
        items=[to_out(row, user) for row in rows], total=total, page=page, page_size=page_size
    )


@router.get("/summary")
async def appointment_summary(
    session: DbSession,
    user: AuthUser,
    on: Annotated[date | None, Query(alias="date")] = None,
) -> AppointmentSummaryOut:
    day = on or clinic_today(user)
    summary = await queries.day_summary(session, user.clinic_id, day, _own_doctor_scope(user, None))
    return AppointmentSummaryOut(
        date=day, total=summary.total, by_status=summary.by_status, by_source=summary.by_source
    )


@router.get("/{appointment_id}")
async def get_appointment(
    appointment_id: UUID, session: DbSession, user: AuthUser
) -> AppointmentDetailOut:
    row = await queries.get_appointment(session, user.clinic_id, appointment_id)
    if row is None or (
        user.role == UserRole.DOCTOR and row[0].doctor_id != _own_doctor_scope(user, None)
    ):
        raise not_found("Appointment")
    events = await queries.appointment_events(session, appointment_id)
    return AppointmentDetailOut(
        **to_out(row, user).model_dump(),
        events=[
            AppointmentEventOut(
                id=event.id,
                from_status=event.from_status,
                to_status=event.to_status,
                actor_type=event.actor_type,
                channel=event.channel,
                changed_by_name=name,
                note=event.note,
                created_at=event.created_at,
            )
            for event, name in events
        ],
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    body: AppointmentCreate, session: DbSession, user: FrontDeskUser
) -> AppointmentOut:
    data = NewAppointment(
        patient_id=body.patient_id,
        doctor_id=body.doctor_id,
        starts_at=body.starts_at,
        source=AppointmentSource(body.source),
        reason_for_visit=body.reason_for_visit,
        notes=body.notes,
        squeeze_in=body.squeeze_in,
    )
    appointment = unwrap(await create_appointment(session, data, staff_actor(user)))
    return to_out(await queries.get_appointment_row(session, user.clinic_id, appointment), user)


@router.post("/{appointment_id}/status")
async def change_status(
    appointment_id: UUID, body: StatusUpdate, session: DbSession, user: AuthUser
) -> AppointmentOut:
    if body.status == AppointmentStatus.COMPLETED:
        # Completing also finalizes the visit's draft consultation, in the same transaction.
        done = unwrap(
            await complete_visit(session, staff_actor(user), appointment_id, note=body.note)
        )
        appointment = done.appointment
    else:
        appointment = unwrap(
            await update_appointment_status(
                session, appointment_id, body.status, staff_actor(user), note=body.note
            )
        )
    return to_out(await queries.get_appointment_row(session, user.clinic_id, appointment), user)


@router.post("/{appointment_id}/reschedule")
async def reschedule(
    appointment_id: UUID, body: RescheduleIn, session: DbSession, user: FrontDeskUser
) -> AppointmentOut:
    appointment = unwrap(
        await reschedule_appointment(
            session, appointment_id, body.starts_at, staff_actor(user), squeeze_in=body.squeeze_in
        )
    )
    return to_out(await queries.get_appointment_row(session, user.clinic_id, appointment), user)


@router.post("/{appointment_id}/approve")
async def approve(appointment_id: UUID, session: DbSession, user: FrontDeskUser) -> AppointmentOut:
    appointment = unwrap(await approve_appointment(session, appointment_id, staff_actor(user)))
    return to_out(await queries.get_appointment_row(session, user.clinic_id, appointment), user)


@router.post("/{appointment_id}/reject")
async def reject(
    appointment_id: UUID, body: RejectIn, session: DbSession, user: FrontDeskUser
) -> AppointmentOut:
    appointment = unwrap(
        await reject_appointment(session, appointment_id, staff_actor(user), body.reason)
    )
    return to_out(await queries.get_appointment_row(session, user.clinic_id, appointment), user)
