from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.doctors import to_out as doctor_out
from app.api.lab_catalog import lab_test_out, lab_test_spec
from app.api.results import not_found, unwrap
from app.core.errors import AppError
from app.deps import AdminUser, DbSession, clinic_today
from app.schemas.admin import UserCreate, UserOut, UserUpdate
from app.schemas.doctors import (
    DoctorCreate,
    DoctorOut,
    DoctorUpdate,
    LeaveCreatedOut,
    LeaveIn,
    SchedulesReplace,
)
from app.schemas.labs import (
    ClinicSettingsOut,
    ClinicSettingsUpdate,
    LabTestActive,
    LabTestIn,
    LabTestOut,
)
from app.services import doctors as doctor_service
from app.services import users as user_service
from app.services.labs import catalog as lab_catalog

router = APIRouter(prefix="/admin", tags=["admin"])

AuthAdminDep = Annotated[user_service.AuthAdmin, Depends(user_service.get_auth_admin)]


def user_out(user: user_service.StaffUser) -> UserOut:
    p = user.profile
    return UserOut(
        id=p.id,
        email=user.email,
        full_name=p.full_name,
        phone=p.phone,
        role=p.role,
        is_active=p.is_active,
        doctor_id=user.doctor_id,
        created_at=p.created_at,
    )


# --- Staff accounts --------------------------------------------------------------------------


@router.get("/users")
async def list_users(session: DbSession, admin: AdminUser) -> list[UserOut]:
    return [user_out(u) for u in await user_service.list_users(session, admin.clinic_id)]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate, session: DbSession, admin: AdminUser, auth_admin: AuthAdminDep
) -> UserOut:
    created = unwrap(
        await user_service.create_user(
            session,
            auth_admin,
            admin.clinic_id,
            email=body.email,
            password=body.password,
            full_name=body.full_name,
            phone=body.phone,
            role=body.role,
            doctor_id=body.doctor_id,
        )
    )
    return user_out(created)


@router.patch("/users/{user_id}")
async def update_user(
    user_id: UUID, body: UserUpdate, session: DbSession, admin: AdminUser
) -> UserOut:
    changes = body.model_dump(exclude_unset=True)
    if user_id == admin.id and changes.get("is_active") is False:
        raise AppError(422, "VALIDATION", "You cannot deactivate your own account.")
    return user_out(
        unwrap(await user_service.update_user(session, admin.clinic_id, user_id, changes))
    )


# --- Doctors, schedules, leave ---------------------------------------------------------------


async def _doctor(session: DbSession, admin: AdminUser, doctor_id: UUID) -> DoctorOut:
    today = clinic_today(admin)
    items = await doctor_service.list_doctors(
        session, admin.clinic_id, today, include_inactive=True, doctor_id=doctor_id
    )
    if not items:
        raise not_found("Doctor")
    return doctor_out(items[0], today)


@router.post("/doctors", status_code=status.HTTP_201_CREATED)
async def create_doctor(body: DoctorCreate, session: DbSession, admin: AdminUser) -> DoctorOut:
    doctor = await doctor_service.create_doctor(session, admin.clinic_id, body.model_dump())
    return await _doctor(session, admin, doctor.id)


@router.patch("/doctors/{doctor_id}")
async def update_doctor(
    doctor_id: UUID, body: DoctorUpdate, session: DbSession, admin: AdminUser
) -> DoctorOut:
    changes = body.model_dump(exclude_unset=True)
    if any(changes.get(k, "") is None for k in ("full_name", "specialization")):
        raise AppError(422, "VALIDATION", "Name and specialization are required.")
    unwrap(await doctor_service.update_doctor(session, admin.clinic_id, doctor_id, changes))
    return await _doctor(session, admin, doctor_id)


@router.put("/doctors/{doctor_id}/schedules")
async def replace_schedules(
    doctor_id: UUID, body: SchedulesReplace, session: DbSession, admin: AdminUser
) -> DoctorOut:
    shifts = [(s.weekday, s.start_time, s.end_time) for s in body.schedules]
    unwrap(await doctor_service.replace_schedules(session, admin.clinic_id, doctor_id, shifts))
    return await _doctor(session, admin, doctor_id)


@router.post("/doctors/{doctor_id}/leaves", status_code=status.HTTP_201_CREATED)
async def add_leave(
    doctor_id: UUID, body: LeaveIn, session: DbSession, admin: AdminUser
) -> LeaveCreatedOut:
    created = unwrap(
        await doctor_service.add_leave(
            session, admin.clinic_id, doctor_id, body.leave_date, body.reason
        )
    )
    return LeaveCreatedOut(
        id=created.leave.id,
        leave_date=created.leave.leave_date,
        reason=created.leave.reason,
        affected_appointments=created.affected_appointments,
    )


@router.delete("/leaves/{leave_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_leave(leave_id: UUID, session: DbSession, admin: AdminUser) -> Response:
    if not await doctor_service.delete_leave(session, admin.clinic_id, leave_id):
        raise not_found("Leave")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Lab catalog and clinic settings
# ---------------------------------------------------------------------------


@router.get("/lab-tests")
async def list_lab_tests(session: DbSession, admin: AdminUser) -> list[LabTestOut]:
    return [lab_test_out(t) for t in await lab_catalog.load_catalog(session, admin.clinic_id)]


@router.post("/lab-tests", status_code=status.HTTP_201_CREATED)
async def create_lab_test(body: LabTestIn, session: DbSession, admin: AdminUser) -> LabTestOut:
    return lab_test_out(
        unwrap(await lab_catalog.create_test(session, admin.clinic_id, lab_test_spec(body)))
    )


@router.put("/lab-tests/{test_id}")
async def update_lab_test(
    test_id: UUID, body: LabTestIn, session: DbSession, admin: AdminUser
) -> LabTestOut:
    return lab_test_out(
        unwrap(
            await lab_catalog.update_test(session, admin.clinic_id, test_id, lab_test_spec(body))
        )
    )


@router.patch("/lab-tests/{test_id}")
async def set_lab_test_active(
    test_id: UUID, body: LabTestActive, session: DbSession, admin: AdminUser
) -> LabTestOut:
    return lab_test_out(
        unwrap(await lab_catalog.set_test_active(session, admin.clinic_id, test_id, body.is_active))
    )


@router.get("/clinic-settings")
async def get_clinic_settings(session: DbSession, admin: AdminUser) -> ClinicSettingsOut:
    return ClinicSettingsOut(
        lab_requires_verification=await lab_catalog.requires_verification(session, admin.clinic_id)
    )


@router.put("/clinic-settings")
async def update_clinic_settings(
    body: ClinicSettingsUpdate, session: DbSession, admin: AdminUser
) -> ClinicSettingsOut:
    value = await lab_catalog.set_requires_verification(
        session, admin.clinic_id, body.lab_requires_verification
    )
    return ClinicSettingsOut(lab_requires_verification=value)
