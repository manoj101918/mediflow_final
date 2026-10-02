from fastapi import APIRouter

from app.deps import AuthUser
from app.schemas.me import ClinicOut, MeOut

router = APIRouter(tags=["me"])


@router.get("/me")
async def get_me(user: AuthUser) -> MeOut:
    return MeOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        clinic=ClinicOut(id=user.clinic_id, name=user.clinic_name, timezone=user.clinic_timezone),
        doctor_id=user.doctor_id,
    )
