"""Shared setup for lab tests: a clinic with the starter catalog and every lab-related role.

`LabWorld` drives the workflow through the API, so tests read like the screens:
doctor orders -> lab collects -> enters values -> submits -> supervisor verifies (releases).
"""

import uuid
from datetime import date
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy import text

from app.db.models import UserRole
from tests.conftest import ClinicFixture, auth


class LabWorld:
    """doc_a has Ravi (male, 56) in consultation; doc_b is another doctor of the clinic."""

    def __init__(self, clinic: ClinicFixture, client: AsyncClient) -> None:
        self.clinic = clinic
        self.client = client

    async def build(self) -> "LabWorld":
        c = self.clinic
        self.tests = await c.add_lab_catalog()
        self.desk = await c.staff(UserRole.RECEPTIONIST)
        self.admin = await c.staff(UserRole.ADMIN)
        self.doc_a = await c.staff(UserRole.DOCTOR)
        self.doc_b = await c.staff(UserRole.DOCTOR)
        self.tech = await c.staff(UserRole.LAB_TECHNICIAN)
        self.head = await c.staff(UserRole.LAB_SUPERVISOR)
        assert self.doc_a.doctor_id and self.doc_b.doctor_id
        self.ravi = await c.add_patient("Ravi Kumar", "+919848012345")
        self.sunita = await c.add_patient("Sunita Rao", "+919848012346")
        await self.demographics(self.ravi, "male", date(1970, 1, 1))
        await self.demographics(self.sunita, "female", date(1985, 6, 1))
        self.visit = await c.add_appointment(
            self.doc_a.doctor_id, self.ravi, status="in_consultation"
        )
        return self

    async def demographics(self, patient: uuid.UUID, gender: str, dob: date) -> None:
        async with self.clinic.sessionmaker() as session, session.begin():
            await session.execute(
                text(
                    "update public.patients set gender = cast(:g as public.gender), "
                    "date_of_birth = :dob where id = :id"
                ),
                {"g": gender, "dob": dob, "id": patient},
            )

    async def scalar(self, sql: str, **params: Any) -> Any:
        async with self.clinic.sessionmaker() as session:
            return await session.scalar(text(sql), params)

    # -- doctor ------------------------------------------------------------

    async def order(
        self,
        *codes: str,
        user: uuid.UUID | None = None,
        appointment: uuid.UUID | None = None,
        **body: Any,
    ) -> Response:
        return await self.client.post(
            f"/api/appointments/{appointment or self.visit}/lab-orders",
            json={"test_ids": [str(self.tests[c]) for c in codes], **body},
            headers=auth(user or self.doc_a.user_id),
        )

    async def ordered(self, *codes: str, **body: Any) -> dict[str, Any]:
        r = await self.order(*codes, **body)
        assert r.status_code == 201, r.text
        return dict(r.json())

    # -- lab -----------------------------------------------------------------

    async def detail(self, order_id: str, user: uuid.UUID | None = None) -> dict[str, Any]:
        r = await self.client.get(
            f"/api/lab/orders/{order_id}", headers=auth(user or self.tech.user_id)
        )
        assert r.status_code == 200, r.text
        return dict(r.json())

    async def collect(
        self, order_id: str, item_ids: list[str], user: uuid.UUID | None = None
    ) -> Response:
        return await self.client.post(
            f"/api/lab/orders/{order_id}/collect",
            json={"item_ids": item_ids},
            headers=auth(user or self.tech.user_id),
        )

    @staticmethod
    def item(detail: dict[str, Any], test_code: str) -> dict[str, Any]:
        return dict(next(i for i in detail["items"] if i["test_code"] == test_code))

    @staticmethod
    def param_ids(item: dict[str, Any]) -> dict[str, str]:
        return {p["code"]: p["id"] for p in item["parameters"]}

    async def save(
        self,
        detail: dict[str, Any],
        test_code: str,
        values: dict[str, Any],
        *,
        confirm: bool = False,
        user: uuid.UUID | None = None,
    ) -> Response:
        item = self.item(detail, test_code)
        ids = self.param_ids(item)
        return await self.client.put(
            f"/api/lab/items/{item['id']}/results",
            json={
                "values": [{"parameter_id": ids[k], "value": v} for k, v in values.items()],
                "confirm_critical": confirm,
            },
            headers=auth(user or self.tech.user_id),
        )

    async def act(
        self, item_id: str, action: str, user: uuid.UUID | None = None, **body: Any
    ) -> Response:
        return await self.client.post(
            f"/api/lab/items/{item_id}/{action}",
            json=body or None,
            headers=auth(user or self.tech.user_id),
        )

    async def released(
        self, codes_values: dict[str, dict[str, Any]], *, confirm: bool = False, **order: Any
    ) -> dict[str, Any]:
        """Order, collect, enter, submit and verify (release) every test; returns the detail."""
        created = await self.ordered(*codes_values, **order)
        r = await self.collect(created["id"], [i["id"] for i in created["items"]])
        assert r.status_code == 200, r.text
        detail = r.json()
        for code, values in codes_values.items():
            r = await self.save(detail, code, values, confirm=confirm)
            assert r.status_code == 200, r.text
            item = self.item(detail, code)
            r = await self.act(item["id"], "submit")
            assert r.status_code == 200, r.text
            r = await self.act(item["id"], "verify", self.head.user_id)
            assert r.status_code == 200, r.text
            detail = r.json()
        return dict(detail)
