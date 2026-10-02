"""Lab order lifecycle through the API: ordering, collection, results, verification, release."""

import asyncio
import re

import pytest
from httpx import AsyncClient

from app.db.models import LabPriority, UserRole
from app.services.labs.orders import NewLabOrder, create_order
from tests.conftest import ClinicFixture, auth
from tests.lab_utils import LabWorld


@pytest.fixture
async def lab(clinic: ClinicFixture, client: AsyncClient) -> LabWorld:
    return await LabWorld(clinic, client).build()


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


async def test_doctor_orders_tests_for_own_visit(lab: LabWorld) -> None:
    created = await lab.ordered("HBA1C", "LIPID", priority="urgent", clinical_note="Diabetic")
    assert re.fullmatch(r"LAB-\d{8}-0001", created["order_number"])
    assert created["status"] == "ordered"
    assert created["priority"] == "urgent"
    assert [i["test_code"] for i in created["items"]] == ["HBA1C", "LIPID"]
    assert {i["status"] for i in created["items"]} == {"ordered"}
    second = await lab.ordered("CBC")
    assert second["order_number"].endswith("-0002")

    listed = await lab.client.get(
        f"/api/appointments/{lab.visit}/lab-orders", headers=auth(lab.doc_b.user_id)
    )
    assert [o["order_number"] for o in listed.json()] == [
        created["order_number"],
        second["order_number"],
    ]
    events = await lab.scalar(
        "select count(*) from public.lab_order_events where order_id = :o and event = 'ordered'",
        o=created["id"],
    )
    assert events == 1


async def test_ordering_rules(lab: LabWorld) -> None:
    # Another doctor's appointment does not exist for them.
    assert (await lab.order("CBC", user=lab.doc_b.user_id)).status_code == 404
    # Only while the patient is checked in / in consultation.
    assert lab.doc_a.doctor_id is not None
    booked = await lab.clinic.add_appointment(lab.doc_a.doctor_id, lab.sunita, status="scheduled")
    r = await lab.order("CBC", appointment=booked)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "INVALID_TRANSITION"
    # Reception and lab staff cannot order.
    for user in (lab.desk, lab.tech):
        assert (await lab.order("CBC", user=user.user_id)).status_code == 403
    # Inactive tests cannot be ordered.
    admin = auth(lab.admin.user_id)
    await lab.client.patch(
        f"/api/admin/lab-tests/{lab.tests['ESR']}", json={"is_active": False}, headers=admin
    )
    r = await lab.order("ESR")
    assert r.status_code == 422
    assert (await lab.order()).status_code == 422


async def test_concurrent_orders_get_distinct_numbers(lab: LabWorld, clinic: ClinicFixture) -> None:
    async def one() -> str:
        async with clinic.sessionmaker() as session:
            result = await create_order(
                session,
                lab.doc_a,
                lab.visit,
                NewLabOrder([lab.tests["CBC"]], LabPriority.ROUTINE),
            )
            return result.unwrap().order_number

    numbers = await asyncio.gather(*(one() for _ in range(6)))
    assert len(set(numbers)) == 6
    assert sorted(int(n.rsplit("-", 1)[1]) for n in numbers) == [1, 2, 3, 4, 5, 6]


async def test_repeat_last_order(lab: LabWorld) -> None:
    r = await lab.client.get(
        f"/api/patients/{lab.ravi}/lab-orders/last", headers=auth(lab.doc_b.user_id)
    )
    assert r.json() == {"test_ids": []}
    await lab.ordered("THYROID", "CBC")
    r = await lab.client.get(
        f"/api/patients/{lab.ravi}/lab-orders/last", headers=auth(lab.doc_b.user_id)
    )
    assert r.json()["test_ids"] == [str(lab.tests["THYROID"]), str(lab.tests["CBC"])]


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


async def test_cancellation_rules(lab: LabWorld) -> None:
    created = await lab.ordered("CBC", "ESR")
    cbc, esr = created["items"]
    url = f"/api/lab/orders/{created['id']}/cancel"
    # Another doctor may not cancel; the lab must give a reason.
    r = await lab.client.post(url, json={}, headers=auth(lab.doc_b.user_id))
    assert r.status_code == 403
    r = await lab.client.post(url, json={"item_ids": [esr["id"]]}, headers=auth(lab.tech.user_id))
    assert r.status_code == 422

    # Once collected, a test can no longer be cancelled.
    assert (await lab.collect(created["id"], [cbc["id"]])).status_code == 200
    r = await lab.client.post(url, json={"item_ids": [cbc["id"]]}, headers=auth(lab.doc_a.user_id))
    assert r.status_code == 409

    r = await lab.client.post(
        url, json={"item_ids": [esr["id"]], "reason": "Not needed"}, headers=auth(lab.doc_a.user_id)
    )
    assert r.status_code == 200, r.text
    statuses = {i["test_code"]: i["status"] for i in r.json()["items"]}
    assert statuses == {"CBC": "sample_collected", "ESR": "cancelled"}
    assert r.json()["status"] == "in_progress"


async def test_cancel_whole_order(lab: LabWorld) -> None:
    created = await lab.ordered("CBC", "ESR")
    r = await lab.client.post(
        f"/api/lab/orders/{created['id']}/cancel",
        json={"reason": "Patient declined"},
        headers=auth(lab.tech.user_id),
    )
    assert r.json()["status"] == "cancelled"
    assert r.json()["cancelled_reason"] == "Patient declined"


# ---------------------------------------------------------------------------
# Collection, rejection, results
# ---------------------------------------------------------------------------


async def test_collection_groups_tubes_by_sample_and_container(lab: LabWorld) -> None:
    created = await lab.ordered("HBA1C", "CBC", "LIPID", "URINE")
    r = await lab.collect(created["id"], [i["id"] for i in created["items"]])
    assert r.status_code == 200, r.text
    detail = r.json()
    samples = detail["order"]["samples"]
    # HbA1c + CBC share an EDTA tube; lipid (plain) and urine get their own.
    assert len(samples) == 3
    assert all(re.fullmatch(r"S-\d{6}-\d{4}", s["sample_code"]) for s in samples)
    by_test = {i["test_code"]: i["sample_code"] for i in detail["items"]}
    assert by_test["HBA1C"] == by_test["CBC"] != by_test["LIPID"]
    assert detail["order"]["status"] == "in_progress"
    # Collecting again is not a valid move.
    again = await lab.collect(created["id"], [created["items"][0]["id"]])
    assert again.status_code == 409


async def test_reject_and_recollect(lab: LabWorld) -> None:
    created = await lab.ordered("ELEC")
    detail = (await lab.collect(created["id"], [created["items"][0]["id"]])).json()
    assert (await lab.save(detail, "ELEC", {"NA": 140})).status_code == 200
    sample = detail["order"]["samples"][0]
    r = await lab.client.post(
        f"/api/lab/samples/{sample['id']}/reject",
        json={"reason": "Haemolysed"},
        headers=auth(lab.tech.user_id),
    )
    assert r.status_code == 200, r.text
    item = lab.item(r.json(), "ELEC")
    assert item["status"] == "sample_rejected"
    assert item["rejection_reason"] == "Haemolysed"
    assert item["results"] == []  # the draft belonged to the rejected tube

    r = await lab.collect(created["id"], [item["id"]])
    item = lab.item(r.json(), "ELEC")
    assert item["status"] == "sample_collected"
    assert item["sample_code"] != sample["sample_code"]
    events = await lab.scalar(
        "select string_agg(event, ',' order by id) from public.lab_order_events "
        "where order_id = :o",
        o=created["id"],
    )
    assert events == "ordered,collected,results_saved,rejected,recollected"


async def test_results_are_flagged_with_the_patients_range(lab: LabWorld) -> None:
    created = await lab.ordered("CBC")
    detail = (await lab.collect(created["id"], [created["items"][0]["id"]])).json()
    hb = next(p for p in lab.item(detail, "CBC")["parameters"] if p["code"] == "HB")
    assert hb["range"]["label"] == "13.0 - 17.0"  # Ravi is male
    r = await lab.save(detail, "CBC", {"HB": 12.4, "TLC": "8.2", "PLT": 250})
    assert r.status_code == 200, r.text
    results = {x["parameter_code"]: x for x in lab.item(r.json(), "CBC")["results"]}
    assert results["HB"]["flag"] == "low"
    assert results["HB"]["range_label"] == "13.0 - 17.0"
    assert results["TLC"]["flag"] == "normal"
    # Clearing a value removes the draft row.
    r = await lab.save(r.json(), "CBC", {"PLT": None})
    assert "PLT" not in {x["parameter_code"] for x in lab.item(r.json(), "CBC")["results"]}


async def test_invalid_values_and_critical_confirmation(lab: LabWorld) -> None:
    created = await lab.ordered("ELEC", "URINE")
    detail = (await lab.collect(created["id"], [i["id"] for i in created["items"]])).json()
    assert (await lab.save(detail, "ELEC", {"K": "high"})).status_code == 422
    assert (await lab.save(detail, "URINE", {"PROT": "lots"})).status_code == 422
    r = await lab.save(detail, "ELEC", {"K": 6.8})
    assert r.status_code == 422
    assert "Potassium" in r.json()["error"]["message"]
    r = await lab.save(detail, "ELEC", {"K": 6.8}, confirm=True)
    assert r.status_code == 200
    assert lab.item(r.json(), "ELEC")["results"][0]["flag"] == "critical_high"
    r = await lab.save(detail, "URINE", {"PROT": "2+", "KET": "negative"})
    flags = {x["parameter_code"]: x["flag"] for x in lab.item(r.json(), "URINE")["results"]}
    assert flags == {"PROT": "abnormal", "KET": "normal"}


# ---------------------------------------------------------------------------
# Submit, verify, send back, release
# ---------------------------------------------------------------------------


async def test_verification_flow(lab: LabWorld) -> None:
    created = await lab.ordered("HBA1C")
    detail = (await lab.collect(created["id"], [created["items"][0]["id"]])).json()
    item_id = lab.item(detail, "HBA1C")["id"]
    # Nothing to submit yet.
    assert (await lab.act(item_id, "submit")).status_code == 422
    await lab.save(detail, "HBA1C", {"HBA1C": 6.9})
    assert (await lab.act(item_id, "submit")).status_code == 200
    # With verification on, the technician can neither verify nor release.
    assert (await lab.act(item_id, "verify")).status_code == 403
    r = await lab.act(item_id, "release")
    assert r.status_code == 403
    # Doctors and reception are not lab staff.
    for user in (lab.doc_a, lab.desk):
        assert (await lab.act(item_id, "verify", user.user_id)).status_code == 403

    r = await lab.act(item_id, "send-back", lab.head.user_id, comment="Recheck calibration")
    assert r.status_code == 200
    item = lab.item(r.json(), "HBA1C")
    assert item["status"] == "sample_collected"
    assert item["return_comment"] == "Recheck calibration"
    assert item["results"][0]["value_numeric"] == 6.9  # values are kept

    await lab.act(item_id, "submit")
    r = await lab.act(item_id, "verify", lab.head.user_id)
    assert r.status_code == 200, r.text
    item = lab.item(r.json(), "HBA1C")
    assert item["status"] == "released"
    assert item["verified_at"] and item["released_at"]
    assert r.json()["order"]["status"] == "released"
    assert (await lab.save(r.json(), "HBA1C", {"HBA1C": 7.0})).status_code == 409


async def test_release_without_verification(lab: LabWorld) -> None:
    await lab.clinic.set_lab_verification(False)
    created = await lab.ordered("FBS")
    detail = (await lab.collect(created["id"], [created["items"][0]["id"]])).json()
    item_id = lab.item(detail, "FBS")["id"]
    await lab.save(detail, "FBS", {"FBS": 132})
    await lab.act(item_id, "submit")
    r = await lab.act(item_id, "release")
    assert r.status_code == 200, r.text
    assert lab.item(r.json(), "FBS")["status"] == "released"
    assert lab.item(r.json(), "FBS")["verified_at"] is None


async def test_partial_release(lab: LabWorld) -> None:
    created = await lab.ordered("HBA1C", "LIPID")
    detail = (await lab.collect(created["id"], [i["id"] for i in created["items"]])).json()
    await lab.save(detail, "HBA1C", {"HBA1C": 7.4})
    hba1c = lab.item(detail, "HBA1C")["id"]
    await lab.act(hba1c, "submit")
    r = await lab.act(hba1c, "verify", lab.head.user_id)
    assert r.json()["order"]["status"] == "partially_released"

    # The doctor sees released values only.
    doctor_view = await lab.client.get(
        f"/api/patients/{lab.ravi}/lab-results", headers=auth(lab.doc_b.user_id)
    )
    [order] = doctor_view.json()
    values = {i["test_code"]: i["results"] for i in order["items"]}
    assert values["HBA1C"][0]["flag"] == "high"
    assert values["LIPID"] == []


async def test_worklist_tabs_and_search(lab: LabWorld) -> None:
    routine = await lab.ordered("CBC")
    stat = await lab.ordered("ELEC", priority="stat")
    headers = auth(lab.tech.user_id)
    r = await lab.client.get("/api/lab/worklist", params={"tab": "to_collect"}, headers=headers)
    assert [row["order_id"] for row in r.json()] == [stat["id"], routine["id"]]  # stat first
    row = r.json()[1]
    assert row["patient_name"] == "Ravi Kumar"
    assert row["patient_age"] == 56
    assert row["counts"] == {"ordered": 1}

    await lab.collect(routine["id"], [routine["items"][0]["id"]])
    tabs = {}
    for tab in ("to_collect", "in_progress", "awaiting_verification"):
        r = await lab.client.get("/api/lab/worklist", params={"tab": tab}, headers=headers)
        tabs[tab] = [row["order_id"] for row in r.json()]
    assert tabs == {
        "to_collect": [stat["id"]],
        "in_progress": [routine["id"]],
        "awaiting_verification": [],
    }
    for q in ("ravi", "2345", routine["order_number"]):
        r = await lab.client.get(
            "/api/lab/worklist", params={"tab": "in_progress", "q": q}, headers=headers
        )
        assert [row["order_id"] for row in r.json()] == [routine["id"]], q
    r = await lab.client.get(
        "/api/lab/worklist", params={"tab": "in_progress", "q": "sunita"}, headers=headers
    )
    assert r.json() == []
    # Only lab staff have a worklist.
    r = await lab.client.get("/api/lab/worklist", headers=auth(lab.doc_a.user_id))
    assert r.status_code == 403


@pytest.mark.parametrize("role", [UserRole.LAB_TECHNICIAN, UserRole.LAB_SUPERVISOR])
async def test_lab_catalog_for_doctors_and_lab(lab: LabWorld, role: UserRole) -> None:
    user = lab.tech if role == UserRole.LAB_TECHNICIAN else lab.head
    for who in (user, lab.doc_a):
        r = await lab.client.get("/api/lab/catalog", headers=auth(who.user_id))
        assert r.status_code == 200
        assert {"CBC", "HBA1C"} <= {t["code"] for t in r.json()}
    r = await lab.client.get("/api/lab/catalog", headers=auth(lab.desk.user_id))
    assert r.status_code == 403
