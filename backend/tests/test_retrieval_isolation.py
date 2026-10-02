"""Retrieval never returns another patient's records, even when records are near-identical."""

from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import text

from app.services.rag.retriever import PatientRecordRetriever
from tests.conftest import (
    TEST_EMBEDDING_MODEL,
    ClinicFixture,
    Ingestion,
    auth,
    parse_sse,
)
from tests.pdf_utils import make_pdf
from tests.records_utils import NOTE, Chart

QUERIES = [
    "Metformin dose",
    "HbA1c result",
    "type 2 diabetes diagnosis",
    "blood pressure 140/90",
    "lab report",
    "what changed since the last visit",
]


async def two_similar_patients(client: AsyncClient, clinic: ClinicFixture) -> Chart:
    """Ravi and Sunita get the same visit note and the same lab report."""
    s = await Chart(clinic).build()
    sunita_visit = await clinic.add_appointment(s.doctor_a, s.sunita, status="in_consultation")
    report = make_pdf(["HbA1c 7.4 % (reference < 5.7 %). Fasting glucose 130 mg/dL."])
    for patient, visit in ((s.ravi, s.visit), (s.sunita, sunita_visit)):
        assert (await s.write(client, visit, s.doc_a.user_id, **NOTE)).status_code == 200
        assert (await s.complete(client, visit, s.doc_a.user_id)).status_code == 200
        uploaded = await client.post(
            f"/api/patients/{patient}/reports",
            data={"title": "HbA1c", "report_type": "lab", "report_date": "2026-03-12"},
            files={"file": ("r.pdf", report, "application/pdf")},
            headers=auth(s.desk.user_id),
        )
        assert uploaded.status_code == 201
    return s


async def sources_of(clinic: ClinicFixture, patient: UUID) -> set[UUID]:
    async with clinic.sessionmaker() as session:
        rows = await session.scalars(
            text("select distinct source_id from patient_record_chunks where patient_id = :p"),
            {"p": patient},
        )
        return set(rows)


async def test_zero_cross_patient_chunks(
    client: AsyncClient, clinic: ClinicFixture, ingestion: Ingestion
) -> None:
    s = await two_similar_patients(client, clinic)
    await ingestion.run()
    ravi_sources = await sources_of(clinic, s.ravi)
    sunita_sources = await sources_of(clinic, s.sunita)
    assert ravi_sources and sunita_sources and not ravi_sources & sunita_sources

    async with clinic.sessionmaker() as session:
        for patient, own, other in (
            (s.ravi, ravi_sources, sunita_sources),
            (s.sunita, sunita_sources, ravi_sources),
        ):
            retriever = PatientRecordRetriever(
                session=session,
                embeddings=ingestion.deps.embeddings,
                clinic_id=clinic.id,
                patient_id=patient,
                embedding_model=TEST_EMBEDDING_MODEL,
                top_k=20,
            )
            for query in QUERIES:
                # Vector + full-text (hybrid), and each arm's raw candidates.
                hits = await retriever.search(query)
                assert hits, query
                assert {h.source_id for h in hits} <= own, query
                assert not {h.source_id for h in hits} & other, query
                docs = await retriever.ainvoke(query)
                assert {d.metadata["source_id"] for d in docs} <= {str(x) for x in own}
            recent = await retriever.recent("consultation", 50)
            assert recent and {h.source_id for h in recent} <= own
            # Even when asked directly for another patient's chunk ids, nothing comes back.
            other_ids = list(
                await session.scalars(
                    text(
                        "select id from patient_record_chunks where patient_id <> :p "
                        "and clinic_id = :c"
                    ),
                    {"p": patient, "c": clinic.id},
                )
            )
            assert await retriever.fetch(other_ids) == []


async def test_chat_cites_only_this_patient(
    client: AsyncClient, clinic: ClinicFixture, ingestion: Ingestion, rag: object
) -> None:
    s = await two_similar_patients(client, clinic)
    await ingestion.run()
    ravi_sources = {str(x) for x in await sources_of(clinic, s.ravi)} | {str(s.ravi)}
    response = await client.post(
        f"/api/patients/{s.ravi}/chat",
        json={"message": "What was the HbA1c result in the lab report?"},
        headers=auth(s.doc_c.user_id),
    )
    assert response.status_code == 200, response.text
    events = dict(parse_sse(response.text))
    cited = {c["source_id"] for c in events["citations"]["citations"]}
    assert cited and cited <= ravi_sources
