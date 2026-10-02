"""Release side effects, alerts, inbox, amendments, snapshots, delta checks and indexing."""

from typing import Any

import pytest
from httpx import AsyncClient

from app.services.labs import workflow
from tests.conftest import ClinicFixture, Ingestion, auth
from tests.lab_utils import LabWorld


@pytest.fixture
async def lab(clinic: ClinicFixture, client: AsyncClient) -> LabWorld:
    return await LabWorld(clinic, client).build()


async def _submitted(lab: LabWorld, code: str, values: dict[str, Any], **kw: Any) -> str:
    created = await lab.ordered(code)
    detail = (await lab.collect(created["id"], [created["items"][0]["id"]])).json()
    r = await lab.save(detail, code, values, **kw)
    assert r.status_code == 200, r.text
    item_id = str(lab.item(detail, code)["id"])
    assert (await lab.act(item_id, "submit")).status_code == 200
    return item_id


async def test_release_creates_report_job_and_alert_together(lab: LabWorld) -> None:
    detail = await lab.released({"ELEC": {"NA": 138, "K": 6.6}}, confirm=True)
    order_id = detail["order"]["id"]
    report = await lab.scalar(
        "select row(is_generated, size_bytes, ingestion_status::text, report_type::text, title) "
        "from public.patient_reports where lab_order_id = :o",
        o=order_id,
    )
    assert report == (True, 0, "pending", "lab", f"Lab report {detail['order']['order_number']}")
    assert detail["order"]["report_id"]
    job = await lab.scalar(
        "select status::text from public.ingestion_jobs "
        "where source_type = 'lab_result' and source_id = :o",
        o=order_id,
    )
    assert job == "pending"
    alerts = await lab.scalar(
        "select count(*) from public.lab_critical_alerts where order_id = :o and doctor_id = :d",
        o=order_id,
        d=lab.doc_a.doctor_id,
    )
    assert alerts == 1
    events = await lab.scalar(
        "select string_agg(event, ',' order by id) from public.lab_order_events "
        "where order_id = :o",
        o=order_id,
    )
    assert events.endswith("submitted,verified,released,lab_report_released")


async def test_failed_release_changes_nothing(
    lab: LabWorld, clinic: ClinicFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    item_id = await _submitted(lab, "ELEC", {"K": 6.6}, confirm=True)

    async def broken(*_: object, **__: object) -> None:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(workflow, "enqueue", broken)
    async with clinic.sessionmaker() as session:
        with pytest.raises(RuntimeError):
            await workflow.verify(session, lab.head, item_id)  # type: ignore[arg-type]

    status = await lab.scalar(
        "select status::text from public.lab_order_items where id = :i", i=item_id
    )
    assert status == "result_entered"
    for table in ("patient_reports", "lab_critical_alerts"):
        count = await lab.scalar(
            f"select count(*) from public.{table} where patient_id = :p",  # noqa: S608
            p=lab.ravi,
        )
        assert count == 0, table


async def test_critical_alert_and_acknowledgement(lab: LabWorld) -> None:
    await lab.released({"ELEC": {"K": 6.6}}, confirm=True)
    r = await lab.client.get("/api/lab/alerts", headers=auth(lab.doc_a.user_id))
    [alert] = r.json()
    assert alert["parameter_name"] == "Potassium"
    assert alert["value"] == "6.6"
    assert alert["flag"] == "critical_high"
    assert alert["patient_name"] == "Ravi Kumar"
    # Other doctors don't get it and can't acknowledge it.
    assert (await lab.client.get("/api/lab/alerts", headers=auth(lab.doc_b.user_id))).json() == []
    url = f"/api/lab/alerts/{alert['id']}/acknowledge"
    assert (await lab.client.post(url, json={}, headers=auth(lab.doc_b.user_id))).status_code == 404
    r = await lab.client.post(
        url, json={"note": "Patient called in"}, headers=auth(lab.doc_a.user_id)
    )
    assert r.status_code == 204
    assert (await lab.client.get("/api/lab/alerts", headers=auth(lab.doc_a.user_id))).json() == []
    note = await lab.scalar(
        "select note from public.lab_critical_alerts where id = :a and acknowledged_by = :u",
        a=alert["id"],
        u=lab.doc_a.user_id,
    )
    assert note == "Patient called in"
    acks = await lab.scalar(
        "select count(*) from public.lab_order_events "
        "where event = 'critical_ack' and actor_id = :u",
        u=lab.doc_a.user_id,
    )
    assert acks == 1


async def test_inbox_review_and_amendment(lab: LabWorld) -> None:
    detail = await lab.released({"HBA1C": {"HBA1C": 6.9}})
    order_id = detail["order"]["id"]
    item_id = lab.item(detail, "HBA1C")["id"]
    inbox = (await lab.client.get("/api/lab/inbox", headers=auth(lab.doc_a.user_id))).json()
    assert [(row["order"]["id"], row["abnormal"], row["critical"]) for row in inbox] == [
        (order_id, 1, 0)
    ]
    assert (await lab.client.get("/api/lab/inbox", headers=auth(lab.doc_b.user_id))).json() == []
    assert (
        await lab.client.post(f"/api/lab/orders/{order_id}/review", headers=auth(lab.doc_b.user_id))
    ).status_code == 404
    r = await lab.client.post(f"/api/lab/orders/{order_id}/review", headers=auth(lab.doc_a.user_id))
    assert r.status_code == 200
    assert (await lab.client.get("/api/lab/inbox", headers=auth(lab.doc_a.user_id))).json() == []

    # Amendments: supervisor only (verification on), reason required, released items only.
    ids = lab.param_ids(lab.item(detail, "HBA1C"))
    body = {
        "values": [{"parameter_id": ids["HBA1C"], "value": 7.1}],
        "reason": "Transcription error",
    }
    assert (await lab.act(item_id, "amend", lab.tech.user_id, **body)).status_code == 403
    r = await lab.act(item_id, "amend", lab.head.user_id, **body)
    assert r.status_code == 200, r.text
    item = lab.item(r.json(), "HBA1C")
    [current] = item["results"]
    [old] = item["history"]
    assert (current["value_numeric"], current["version"], current["is_current"]) == (7.1, 2, True)
    assert current["amended_reason"] == "Transcription error"
    assert (old["value_numeric"], old["version"], old["is_current"]) == (6.9, 1, False)
    # Amended results go back to the doctor's inbox, and the report is regenerated.
    inbox = (await lab.client.get("/api/lab/inbox", headers=auth(lab.doc_a.user_id))).json()
    assert [row["order"]["id"] for row in inbox] == [order_id]
    status = await lab.scalar(
        "select ingestion_status::text from public.patient_reports where lab_order_id = :o",
        o=order_id,
    )
    assert status == "pending"

    pending = await lab.ordered("CBC")
    pending_item = pending["items"][0]["id"]
    r = await lab.act(pending_item, "amend", lab.head.user_id, **body)
    assert r.status_code in (409, 422)


async def test_old_results_keep_their_snapshot(lab: LabWorld) -> None:
    detail = await lab.released({"HBA1C": {"HBA1C": 5.8}})
    admin = auth(lab.admin.user_id)
    catalog = (await lab.client.get("/api/admin/lab-tests", headers=admin)).json()
    test = next(t for t in catalog if t["code"] == "HBA1C")
    body = {
        **{k: test[k] for k in ("code", "name", "category", "sample_type", "container")},
        "turnaround_hours": test["turnaround_hours"],
        "parameters": [
            {
                **{k: p[k] for k in ("id", "code", "name", "unit", "value_type", "choices")},
                "decimals": p["decimals"],
                "ranges": [{"low": 4.0, "high": 6.0}],
            }
            for p in test["parameters"]
        ],
    }
    r = await lab.client.put(f"/api/admin/lab-tests/{test['id']}", json=body, headers=admin)
    assert r.status_code == 200, r.text

    results = (
        await lab.client.get(
            f"/api/patients/{lab.ravi}/lab-results", headers=auth(lab.doc_a.user_id)
        )
    ).json()
    old = results[0]["items"][0]["results"][0]
    assert (old["range_label"], old["flag"]) == ("4.0 - 5.6", "high")
    assert results[0]["id"] == detail["order"]["id"]
    new = await lab.released({"HBA1C": {"HBA1C": 5.8}})
    [result] = lab.item(new, "HBA1C")["results"]
    assert (result["range_label"], result["flag"]) == ("4.0 - 6.0", "normal")


async def test_previous_value_and_delta_check(lab: LabWorld) -> None:
    await lab.released({"HBA1C": {"HBA1C": 8.1}, "LIPID": {"LDL": 150}})
    created = await lab.ordered("HBA1C")
    detail = (await lab.collect(created["id"], [created["items"][0]["id"]])).json()
    [param] = lab.item(detail, "HBA1C")["parameters"]
    assert param["previous"]["value_numeric"] == 8.1
    assert param["delta_warning"] is False
    r = await lab.save(detail, "HBA1C", {"HBA1C": 5.0})
    [param] = lab.item(r.json(), "HBA1C")["parameters"]
    assert param["delta_warning"] is True  # 38% change, limit 20%
    # Earlier results of other tests are not part of this order's view.
    codes = {p["code"] for i in r.json()["items"] for p in i["parameters"]}
    assert codes == {"HBA1C"}


async def test_status_counts_without_values(lab: LabWorld) -> None:
    await lab.released({"HBA1C": {"HBA1C": 6.9}})
    await lab.ordered("CBC", "ESR")
    r = await lab.client.get(
        "/api/lab/status-summary",
        params={"day": "2026-01-05"},
        headers=auth(lab.desk.user_id),
    )
    assert r.status_code == 200
    assert r.json() == [{"appointment_id": str(lab.visit), "pending": 2, "ready": 1}]

    r = await lab.client.get(f"/api/patients/{lab.ravi}/lab-orders", headers=auth(lab.desk.user_id))
    assert r.status_code == 200
    body = r.text
    assert "6.9" not in body and "clinical_note" not in body and "results" not in body
    assert [t["status"] for o in r.json() for t in o["tests"]] == ["ordered", "ordered", "released"]


async def test_released_results_are_indexed_once(lab: LabWorld, ingestion: Ingestion) -> None:
    detail = await lab.released({"HBA1C": {"HBA1C": 6.9}, "LIPID": {"LDL": 118, "HDL": 42}})
    order_id = detail["order"]["id"]
    assert await ingestion.run() >= 1
    rows = await lab.scalar(
        "select json_agg(json_build_object('c', content, 'm', metadata) order by chunk_index) "
        "from public.patient_record_chunks where source_type = 'lab_result' and source_id = :o",
        o=order_id,
    )
    assert len(rows) == 2
    hba1c, lipid = rows
    assert "HbA1c 6.9 % (reference 4.0 - 5.6) HIGH" in hba1c["c"]
    assert detail["order"]["order_number"] in hba1c["c"]
    assert hba1c["m"]["order_item_id"] == lab.item(detail, "HBA1C")["id"]
    assert "LDL cholesterol 118 mg/dL (reference < 100) HIGH" in lipid["c"]
    # The generated report row is not embedded as a report of its own.
    reports = await lab.scalar(
        "select count(*) from public.patient_record_chunks c join public.patient_reports r "
        "on r.id = c.source_id where c.source_type = 'report' and r.lab_order_id = :o",
        o=order_id,
    )
    assert reports == 0
