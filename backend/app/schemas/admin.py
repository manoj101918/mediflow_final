from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.db.models import UserRole
from app.schemas.common import Name, ShortText, UtcDateTime

# Format check only; Supabase Auth is the authority. (EmailStr rejects reserved TLDs such as
# .test, which the clinic's dev accounts use.)
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_lower=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    ),
]


class UserOut(BaseModel):
    id: UUID
    email: str | None
    full_name: str
    phone: str | None
    role: UserRole
    is_active: bool
    doctor_id: UUID | None
    created_at: UtcDateTime


class UserCreate(BaseModel):
    email: Email
    password: str = Field(min_length=8, max_length=72)
    full_name: Name
    phone: ShortText = None
    role: UserRole
    # Doctors only: link the login to an existing doctor that has no login yet.
    doctor_id: UUID | None = None

    @model_validator(mode="after")
    def _doctor_link(self) -> Self:
        if self.doctor_id is not None and self.role != UserRole.DOCTOR:
            raise ValueError("Only doctor accounts can be linked to a doctor.")
        return self


class UserUpdate(BaseModel):
    full_name: Name | None = None
    phone: ShortText = None
    is_active: bool | None = None
