"""RLS for the lab tables (Realtime and direct Supabase access with a user's JWT).

Only lab_orders (doctors + lab staff of the clinic) and lab_critical_alerts (the alert's
doctor) are readable by clients; result values and everything else stay backend-only.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.models import UserRole
from tests.conftest import ClinicFixture
from tests.test_rls import Sessions, _query


async def _order_with_alert(
    clinic: ClinicFixture, sessionmaker: Sessions, doctor_id: uuid.UUID
) -> dict[str, uuid.UUID]:
    """An order with one released item, one critical result and its alert (direct SQL)."""
    tests = await clinic.add_lab_catalog()
    patient = await clinic.add_patient(f"Lab RLS {uuid.uuid4().hex[:6]}", "+919811111111")
    appointment = await clinic.add_appointment(doctor_id, patient)
    ids = {k: uuid.uuid4() for k in ("order", "item", "result", "alert")}
    async with sessionmaker() as session, session.begin():
        param = await session.scalar(
            text("select id from public.lab_test_parameters where test_id = :t and code = 'K'"),
            {"t": tests["ELEC"]},
        )
        await session.execute(
            text(
                "insert into public.lab_orders (id, clinic_id, patient_id, ordering_doctor_id, "
                "appointment_id, order_number, status, clinical_note) values (:id, :c, :p, :d, "
                ":a, 'LAB-20260105-0001', 'released', 'on ACE inhibitor')"
            ),
            {"id": ids["order"], "c": clinic.id, "p": patient, "d": doctor_id, "a": appointment},
        )
        await session.execute(
            text(
                "insert into public.lab_order_items (id, order_id, test_id, test_code, test_name, "
                "status, released_at) values (:id, :o, :t, 'ELEC', 'Electrolytes', 'released', "
                "now())"
            ),
            {"id": ids["item"], "o": ids["order"], "t": tests["ELEC"]},
        )
        await session.execute(
            text(
                "insert into public.lab_results (id, order_item_id, parameter_id, parameter_code, "
                "parameter_name, unit, value_type, value_numeric, flag) values (:id, :i, :p, 'K', "
                "'Potassium', 'mmol/L', 'numeric', 6.5, 'critical_high')"
            ),
            {"id": ids["result"], "i": ids["item"], "p": param},
        )
        await session.execute(
            text(
                "insert into public.lab_critical_alerts (id, clinic_id, result_id, order_id, "
                "patient_id, doctor_id) values (:id, :c, :r, :o, :p, :d)"
            ),
            {
                "id": ids["alert"],
                "c": clinic.id,
                "r": ids["result"],
                "o": ids["order"],
                "p": patient,
                "d": doctor_id,
            },
        )
    return ids


@pytest.fixture
async def lab_world(clinic: ClinicFixture, sessionmaker: Sessions) -> dict[str, uuid.UUID]:
    doc_a = await clinic.staff(UserRole.DOCTOR)
    doc_b = await clinic.staff(UserRole.DOCTOR)
    assert doc_a.doctor_id is not None
    ids = await _order_with_alert(clinic, sessionmaker, doc_a.doctor_id)
    ids.update(doc_a=doc_a.user_id, doc_b=doc_b.user_id)
    for role in (
        UserRole.LAB_TECHNICIAN,
        UserRole.LAB_SUPERVISOR,
        UserRole.RECEPTIONIST,
        UserRole.ADMIN,
    ):
        ids[role.value] = (await clinic.staff(role)).user_id
    return ids


async def test_lab_orders_visible_to_doctors_and_lab_only(
    sessionmaker: Sessions, lab_world: dict[str, uuid.UUID]
) -> None:
    order = lab_world["order"]
    for who in ("doc_a", "doc_b", "lab_technician", "lab_supervisor"):
        assert await _query(sessionmaker, lab_world[who], "select id from public.lab_orders") == {
            order
        }, who
    # Reception/admin get status counts from FastAPI; the row carries the clinical note.
    for who in ("receptionist", "admin"):
        assert (
            await _query(sessionmaker, lab_world[who], "select id from public.lab_orders") == set()
        )


async def test_other_clinic_cannot_see_lab_orders(
    sessionmaker: Sessions, lab_world: dict[str, uuid.UUID], other_clinic: ClinicFixture
) -> None:
    for role in (UserRole.DOCTOR, UserRole.LAB_TECHNICIAN):
        outsider = await other_clinic.staff(role)
        assert (
            await _query(sessionmaker, outsider.user_id, "select id from public.lab_orders")
            == set()
        )
        assert (
            await _query(
                sessionmaker, outsider.user_id, "select id from public.lab_critical_alerts"
            )
            == set()
        )


async def test_critical_alert_visible_only_to_its_doctor(
    sessionmaker: Sessions, lab_world: dict[str, uuid.UUID]
) -> None:
    sql = "select id from public.lab_critical_alerts"
    assert await _query(sessionmaker, lab_world["doc_a"], sql) == {lab_world["alert"]}
    for who in ("doc_b", "lab_technician", "lab_supervisor", "receptionist", "admin"):
        assert await _query(sessionmaker, lab_world[who], sql) == set(), who


@pytest.mark.parametrize(
    "table",
    [
        "lab_results",
        "lab_order_items",
        "lab_samples",
        "lab_order_events",
        "lab_tests",
        "lab_test_parameters",
        "lab_reference_ranges",
    ],
)
async def test_backend_only_lab_tables_are_not_readable(
    sessionmaker: Sessions, lab_world: dict[str, uuid.UUID], table: str
) -> None:
    for role, user in (("authenticated", lab_world["doc_a"]), ("anon", None)):
        with pytest.raises(DBAPIError, match="permission denied"):
            sql = f"select 1 from public.{table}"  # noqa: S608 - fixed table names
            await _query(sessionmaker, user, sql, role=role)


async def test_clients_cannot_write_lab_orders(
    sessionmaker: Sessions, lab_world: dict[str, uuid.UUID]
) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        await _query(
            sessionmaker,
            lab_world["lab_supervisor"],
            "update public.lab_orders set status = 'cancelled' returning id",
        )


async def test_released_result_values_are_locked(
    sessionmaker: Sessions, lab_world: dict[str, uuid.UUID]
) -> None:
    async with sessionmaker() as session:
        with pytest.raises(DBAPIError, match="released and cannot be changed"):
            await session.execute(
                text("update public.lab_results set value_numeric = 4.1 where id = :id"),
                {"id": lab_world["result"]},
            )
        await session.rollback()
        # Retiring the row (amendment) is allowed; reviving it is not.
        await session.execute(
            text("update public.lab_results set is_current = false where id = :id"),
            {"id": lab_world["result"]},
        )
        with pytest.raises(DBAPIError, match="released and cannot be changed"):
            await session.execute(
                text("update public.lab_results set is_current = true where id = :id"),
                {"id": lab_world["result"]},
            )
        await session.rollback()


async def test_publication_tables(sessionmaker: Sessions) -> None:
    async with sessionmaker() as session:
        tables: set[str] = set(
            (
                await session.execute(
                    text(
                        "select tablename from pg_publication_tables "
                        "where pubname = 'supabase_realtime'"
                    )
                )
            ).scalars()
        )
    assert {"lab_orders", "lab_critical_alerts"} <= tables
    assert not tables & {"lab_results", "lab_order_items", "lab_samples", "lab_order_events"}
