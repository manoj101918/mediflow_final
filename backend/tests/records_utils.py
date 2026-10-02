"""Shared setup for clinical-record tests."""

import uuid
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy import text

from app.db.models import UserRole
from tests.conftest import ClinicFixture, auth

NOTE = {
    "chief_complaint": "Increased thirst",
    "diagnosis": "Type 2 diabetes mellitus",
    "advice": "Low sugar diet, walk 30 minutes daily",
    "vitals": {"bp_systolic": 140, "bp_diastolic": 90, "weight_kg": 78.5},
    "items": [
        {
            "medicine_name": "Metformin",
            "strength": "500 mg",
            "dosage_form": "tablet",
            "frequency": "1-0-1",
            "timing": "after_food",
            "duration_days": 30,
        }
    ],
}


class Chart:
    """Reception, admin, three linked doctors and two patients.

    doc_a has Ravi in consultation (`visit`); doc_c has never seen Ravi.
    """

    def __init__(self, clinic: ClinicFixture) -> None:
        self.clinic = clinic

    async def build(self) -> "Chart":
        c = self.clinic
        self.desk = await c.staff(UserRole.RECEPTIONIST)
        self.admin = await c.staff(UserRole.ADMIN)
        self.doc_a = await c.staff(UserRole.DOCTOR)
        self.doc_b = await c.staff(UserRole.DOCTOR)
        self.doc_c = await c.staff(UserRole.DOCTOR)
        assert self.doc_a.doctor_id and self.doc_b.doctor_id and self.doc_c.doctor_id
        self.doctor_a: uuid.UUID = self.doc_a.doctor_id
        self.doctor_b: uuid.UUID = self.doc_b.doctor_id
        self.ravi = await c.add_patient("Ravi Kumar", "+919848012345")
        self.sunita = await c.add_patient("Sunita Rao", "+919848012346")
        self.visit = await c.add_appointment(self.doctor_a, self.ravi, status="in_consultation")
        return self

    async def write(
        self, client: AsyncClient, appointment: uuid.UUID, user: uuid.UUID, **body: Any
    ) -> Response:
        return await client.put(
            f"/api/appointments/{appointment}/consultation",
            json=body or NOTE,
            headers=auth(user),
        )

    async def complete(
        self, client: AsyncClient, appointment: uuid.UUID, user: uuid.UUID
    ) -> Response:
        return await client.post(f"/api/appointments/{appointment}/complete", headers=auth(user))

    async def scalar(self, sql: str, **params: Any) -> Any:
        async with self.clinic.sessionmaker() as session:
            return await session.scalar(text(sql), params)
