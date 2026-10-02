"""After release: generated PDF, lab_result chunks, chatbot citations and the patient summary."""

from datetime import date
from io import BytesIO

import pytest
from httpx import AsyncClient
from pypdf import PdfReader

from app.db.models import Patient
from app.services.labs.pdf import ReportData, ReportRow, ReportTest, render_report
from app.services.rag.providers import RagProviders
from app.services.rag.snapshot import patient_summary
from tests.conftest import ClinicFixture, FakeReportStorage, Ingestion, auth, parse_sse
from tests.lab_utils import LabWorld
from tests.pdf_utils import make_pdf


@pytest.fixture
async def lab(clinic: ClinicFixture, client: AsyncClient) -> LabWorld:
    return await LabWorld(clinic, client).build()


def _pdf_text(data: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)


async def test_release_generates_the_pdf_report(
    lab: LabWorld, ingestion: Ingestion, report_storage: FakeReportStorage
) -> None:
    detail = await lab.released(
        {"HBA1C": {"HBA1C": 7.8}, "ELEC": {"K": 6.6, "NA": 138}}, confirm=True
    )
    order_id = detail["order"]["id"]
    await ingestion.run()

    path, size, status, pages = await lab.scalar(
        "select row(storage_path, size_bytes, ingestion_status::text, page_count) "
        "from public.patient_reports where lab_order_id = :o and is_generated",
        o=order_id,
    )
    assert (status, pages) == ("indexed", 1)
    data, content_type = report_storage.files[path]
    assert content_type == "application/pdf" and size == len(data)
    text = _pdf_text(data)
    for expected in (
        "LABORATORY REPORT",
        "Ravi Kumar",
        detail["order"]["order_number"],
        "HbA1c",
        "7.8",
        "HIGH",
        "CRITICAL HIGH",
        "4.0 - 5.6",
    ):
        assert expected in text, expected
    assert "AMENDED" not in text

    # The doctor opens it through a signed URL.
    r = await lab.client.get(
        f"/api/reports/{detail['order']['report_id']}/url", headers=auth(lab.doc_b.user_id)
    )
    assert r.status_code == 200

    # An amendment regenerates the same file as "Amended".
    item = lab.item(detail, "HBA1C")
    ids = lab.param_ids(item)
    r = await lab.act(
        item["id"],
        "amend",
        lab.head.user_id,
        values=[{"parameter_id": ids["HBA1C"], "value": 7.6}],
        reason="Re-run on analyser",
    )
    assert r.status_code == 200, r.text
    await ingestion.run()
    data, _ = report_storage.files[path]
    text = _pdf_text(data)
    assert "AMENDED" in text and "Re-run on analyser" in text and "7.6" in text
    title = await lab.scalar(
        "select title from public.patient_reports where lab_order_id = :o and is_generated",
        o=order_id,
    )
    assert title.endswith("(amended)")
    chunk = await lab.scalar(
        "select string_agg(content, ' ') from public.patient_record_chunks "
        "where source_type = 'lab_result' and source_id = :o",
        o=order_id,
    )
    assert "7.6 %" in chunk and "amended: Re-run on analyser" in chunk and "7.8" not in chunk


# Characters the core PDF fonts cannot encode.
EN_DASH = chr(0x2013)


def test_render_report_is_latin1_safe() -> None:
    data = ReportData(
        clinic_name="Clinic",
        clinic_address="",
        patient_name=f"Zoë {EN_DASH} Test",
        age_sex="40 y / Female",
        order_number="LAB-20261002-0001",
        ordering_doctor="Dr. A",
        ordered_at="02 Oct 2026",
        samples=["S-261002-0001"],
        tests=[
            ReportTest(
                "Thyroid",
                "02 Oct 2026",
                "",
                "",
                [ReportRow("TSH", "5.2", "µIU/mL", f"0.4 {EN_DASH} 4.0", "HIGH", True)],
            )
        ],
        amended=False,
        generated_at="02 Oct 2026",
    )
    rendered = render_report(data)
    assert rendered.pages == 1 and rendered.data.startswith(b"%PDF")


async def test_lab_attachment_is_stored_not_embedded(
    lab: LabWorld, ingestion: Ingestion, report_storage: FakeReportStorage
) -> None:
    detail = await lab.released({"HBA1C": {"HBA1C": 6.9}})
    order_id = detail["order"]["id"]
    pdf = make_pdf(["Analyser printout: HbA1c 6.9 % glycated haemoglobin"])
    files = {"file": ("machine.pdf", pdf, "application/pdf")}
    r = await lab.client.post(
        f"/api/lab/orders/{order_id}/attachment", files=files, headers=auth(lab.doc_a.user_id)
    )
    assert r.status_code == 403
    r = await lab.client.post(
        f"/api/lab/orders/{order_id}/attachment", files=files, headers=auth(lab.tech.user_id)
    )
    assert r.status_code == 201, r.text
    await ingestion.run()
    status = await lab.scalar(
        "select ingestion_status::text from public.patient_reports where id = :r", r=r.json()["id"]
    )
    assert status == "indexed"
    reports = await lab.scalar(
        "select count(*) from public.patient_record_chunks "
        "where source_type = 'report' and patient_id = :p",
        p=lab.ravi,
    )
    assert reports == 0


async def test_chatbot_cites_the_lab_result(
    lab: LabWorld, ingestion: Ingestion, rag: RagProviders
) -> None:
    detail = await lab.released({"THYROID": {"TSH": 8.2, "T3": 110, "T4": 7.0}})
    await ingestion.run()
    r = await lab.client.post(
        f"/api/patients/{lab.ravi}/chat",
        json={"message": "What was the latest TSH result?"},
        headers=auth(lab.doc_b.user_id),
    )
    assert r.status_code == 200, r.text
    events = parse_sse(r.text)
    citations = events[-2][1]["citations"]
    lab_cites = [c for c in citations if c["source_type"] == "lab_result"]
    assert lab_cites, citations
    assert lab_cites[0]["source_id"] == detail["order"]["id"]
    assert lab_cites[0]["item_id"] == lab.item(detail, "THYROID")["id"]
    answer = "".join(d["text"] for name, d in events if name == "token")
    assert "8.2" in answer


async def test_summary_lists_abnormal_values_and_open_criticals(lab: LabWorld) -> None:
    await lab.released({"ELEC": {"K": 6.6, "NA": 138}, "HBA1C": {"HBA1C": 5.2}}, confirm=True)
    async with lab.clinic.sessionmaker() as session:
        patient = await session.get(Patient, lab.ravi)
        assert patient is not None
        summary = await patient_summary(session, patient, date.today())
    assert "Latest abnormal lab values" in summary
    assert "Potassium 6.6 mmol/L (reference 3.5 - 5.1) CRITICAL HIGH" in summary
    assert "Sodium" not in summary and "HbA1c" not in summary  # normal values stay out
    assert "Unacknowledged critical lab results: 1." in summary
