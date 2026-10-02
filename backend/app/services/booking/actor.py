"""Who is performing a booking action.

Staff act from the dashboard; system actors are automated channels (WhatsApp/voice bots).
The booking service makes all permission decisions from the actor, so every channel shares
the same rules.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.db.models import ActorType, UserRole

SystemChannel = Literal["whatsapp", "voice"]


@dataclass(frozen=True)
class StaffActor:
    user_id: UUID
    role: UserRole
    clinic_id: UUID
    # Set for doctors linked to a doctors row; doctors may only act on their own appointments.
    doctor_id: UUID | None = None
    kind: Literal["staff"] = "staff"

    @property
    def actor_type(self) -> ActorType:
        return ActorType.USER

    @property
    def channel(self) -> str:
        return "dashboard"

    @property
    def changed_by(self) -> UUID | None:
        return self.user_id

    @property
    def is_front_desk(self) -> bool:
        return self.role in (UserRole.RECEPTIONIST, UserRole.ADMIN)


@dataclass(frozen=True)
class SystemActor:
    channel: SystemChannel
    clinic_id: UUID
    kind: Literal["system"] = "system"

    @property
    def actor_type(self) -> ActorType:
        return ActorType.SYSTEM

    @property
    def changed_by(self) -> UUID | None:
        return None


Actor = StaffActor | SystemActor
