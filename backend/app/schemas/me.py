from uuid import UUID

from pydantic import BaseModel

from app.db.models import UserRole


class ClinicOut(BaseModel):
    id: UUID
    name: str
    timezone: str


class MeOut(BaseModel):
    id: UUID
    email: str | None
    full_name: str
    role: UserRole
    clinic: ClinicOut
    doctor_id: UUID | None
