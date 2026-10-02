"""The clinic's lab report PDF (fpdf2), rendered from released structured results.

`build_report_data` gathers what the report shows; `render_report` is a pure function from
that data to PDF bytes. Core PDF fonts only support Latin-1, so text is transliterated where
needed (names and units in this clinic are ASCII in practice).
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Clinic,
    Doctor,
    LabItemStatus,
    LabOrder,
    LabOrderItem,
    LabSample,
    Patient,
    Profile,
)
from app.services.booking.timeutil import clinic_tz, local_date, utcnow
from app.services.labs.ranges import ABNORMAL_FLAGS, age_on, format_number
from app.services.labs.render import FLAG_TEXT, released_results


@dataclass(frozen=True)
class ReportRow:
    name: str
    value: str
    unit: str
    reference: str
    flag: str
    abnormal: bool
    note: str = ""


@dataclass(frozen=True)
class ReportTest:
    name: str
    reported_at: str
    entered_by: str
    verified_by: str
    rows: list[ReportRow]


@dataclass(frozen=True)
class ReportData:
    clinic_name: str
    clinic_address: str
    patient_name: str
    age_sex: str
    order_number: str
    ordering_doctor: str
    ordered_at: str
    samples: list[str]
    tests: list[ReportTest]
    amended: bool
    generated_at: str
    pending_tests: list[str] = field(default_factory=list)


def _when(moment: datetime | None, tz: ZoneInfo) -> str:
    if moment is None:
        return ""
    local = moment.astimezone(tz)
    return f"{local.day:02d} {local:%b %Y, %I:%M %p}"


async def _names(session: AsyncSession, ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    rows = await session.execute(select(Profile.id, Profile.full_name).where(Profile.id.in_(ids)))
    return {pid: name for pid, name in rows}


async def build_report_data(session: AsyncSession, order_id: UUID) -> ReportData | None:
    order = await session.get(LabOrder, order_id)
    if order is None:
        return None
    released = await released_results(session, order_id)
    if not released:
        return None
    clinic = await session.get(Clinic, order.clinic_id)
    patient = await session.get(Patient, order.patient_id)
    if clinic is None or patient is None:
        return None
    tz = clinic_tz(clinic.timezone)
    doctor = await session.scalar(
        select(Doctor.full_name).where(Doctor.id == order.ordering_doctor_id)
    )
    samples = (
        await session.scalars(
            select(LabSample)
            .where(LabSample.order_id == order.id, LabSample.rejected_at.is_(None))
            .order_by(LabSample.collected_at)
        )
    ).all()
    staff = await _names(
        session,
        {i.entered_by for i, _ in released if i.entered_by}
        | {i.verified_by for i, _ in released if i.verified_by},
    )
    age = age_on(local_date(order.created_at, tz), patient.date_of_birth, patient.age_years)
    sex = patient.gender.value.title() if patient.gender else ""
    tests: list[ReportTest] = []
    amended = False
    for item, results in released:
        rows = []
        for r in results:
            value = (
                format_number(r.value_numeric)
                if r.value_numeric is not None
                else r.value_text or ""
            )
            note = ""
            if r.version > 1:
                amended = True
                note = f"Amended: {r.amended_reason}"
            rows.append(
                ReportRow(
                    name=r.parameter_name,
                    value=value,
                    unit=r.unit or "",
                    reference=r.range_label or "",
                    flag=FLAG_TEXT.get(r.flag, "") if r.flag else "",
                    abnormal=r.flag in ABNORMAL_FLAGS,
                    note=note,
                )
            )
        tests.append(
            ReportTest(
                name=item.test_name,
                reported_at=_when(item.released_at, tz),
                entered_by=staff.get(item.entered_by, "") if item.entered_by else "",
                verified_by=staff.get(item.verified_by, "") if item.verified_by else "",
                rows=rows,
            )
        )
    pending = (
        await session.scalars(
            select(LabOrderItem.test_name).where(
                LabOrderItem.order_id == order.id,
                LabOrderItem.status.not_in([LabItemStatus.RELEASED, LabItemStatus.CANCELLED]),
            )
        )
    ).all()
    return ReportData(
        clinic_name=clinic.name,
        clinic_address=" | ".join(x for x in (clinic.address, clinic.phone) if x),
        patient_name=patient.full_name,
        age_sex=" / ".join(x for x in (f"{age} y" if age is not None else "", sex) if x),
        order_number=order.order_number,
        ordering_doctor=doctor or "",
        ordered_at=_when(order.created_at, tz),
        samples=[f"{s.sample_code} ({_when(s.collected_at, tz)})" for s in samples],
        tests=tests,
        amended=amended,
        generated_at=_when(utcnow(), tz),
        pending_tests=list(pending),
    )


# Dashes, micro sign, curly quote and <=/>= have no Latin-1 glyph in the core fonts.
_PLAIN = str.maketrans(
    {0x2013: "-", 0x2014: "-", 0x00B5: "u", 0x2019: "'", 0x2264: "<=", 0x2265: ">="}
)


def _latin1(text: str) -> str:
    text = text.translate(_PLAIN)
    return text.encode("latin-1", "replace").decode("latin-1")


class _Report(FPDF):
    def __init__(self, data: ReportData) -> None:
        super().__init__(format="A4")
        self.data = data
        self.set_auto_page_break(auto=True, margin=18)
        self.set_title(_latin1(f"Lab report {data.order_number}"))

    def header(self) -> None:
        d = self.data
        self.set_font("Helvetica", "B", 15)
        self.cell(0, 8, _latin1(d.clinic_name), new_x="LMARGIN", new_y="NEXT")
        if d.clinic_address:
            self.set_font("Helvetica", size=9)
            self.cell(0, 5, _latin1(d.clinic_address), new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "B", 12)
        title = "LABORATORY REPORT" + ("  -  AMENDED" if d.amended else "")
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Helvetica", "I", 8)
        self.cell(
            0,
            5,
            _latin1(
                f"{self.data.order_number} | Generated {self.data.generated_at} | "
                f"Page {self.page_no()}/{{nb}}"
            ),
            align="C",
        )


def _test_table(pdf: FPDF, test: ReportTest, cols: tuple[float, ...], width: float) -> None:
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_fill_color(235, 238, 242)
    pdf.cell(0, 7, _latin1(test.name), fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 9)
    for text, w in zip(
        ("Parameter", "Result", "Unit", "Reference range", "Flag"), cols, strict=True
    ):
        pdf.cell(w, 6, text)
    pdf.ln(6)
    for row in test.rows:
        pdf.set_font("Helvetica", size=9)
        pdf.cell(cols[0], 6, _latin1(row.name))
        pdf.set_font("Helvetica", "B" if row.abnormal else "", 9)
        pdf.cell(cols[1], 6, _latin1(row.value))
        pdf.set_font("Helvetica", size=9)
        pdf.cell(cols[2], 6, _latin1(row.unit))
        pdf.cell(cols[3], 6, _latin1(row.reference))
        pdf.set_font("Helvetica", "B" if row.abnormal else "", 9)
        pdf.cell(cols[4], 6, _latin1(row.flag), new_x="LMARGIN", new_y="NEXT")
        if row.note:
            pdf.set_font("Helvetica", "I", 8)
            pdf.cell(cols[0], 5, "")
            pdf.multi_cell(width - cols[0], 5, _latin1(row.note), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 8)
    people = [f"Reported {test.reported_at}"]
    if test.entered_by:
        people.append(f"entered by {test.entered_by}")
    if test.verified_by:
        people.append(f"verified by {test.verified_by}")
    pdf.cell(0, 5, _latin1(", ".join(people)), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)


@dataclass(frozen=True)
class RenderedReport:
    data: bytes
    pages: int


def render_report(data: ReportData) -> RenderedReport:
    pdf = _Report(data)
    pdf.alias_nb_pages()
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin

    def pair(label: str, value: str) -> None:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(32, 6, label)
        pdf.set_font("Helvetica", size=10)
        pdf.cell(width / 2 - 32, 6, _latin1(value))

    pair("Patient", data.patient_name)
    pair("Order no.", data.order_number)
    pdf.ln(6)
    pair("Age / Sex", data.age_sex)
    pair("Ordered by", data.ordering_doctor)
    pdf.ln(6)
    pair("Ordered", data.ordered_at)
    pair("Samples", ", ".join(data.samples[:2]))
    pdf.ln(6)
    for extra in data.samples[2:]:
        pdf.cell(width / 2, 6, "")
        pdf.cell(32, 6, "")
        pdf.cell(width / 2 - 32, 6, _latin1(extra), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    cols = (width * 0.36, width * 0.17, width * 0.15, width * 0.2, width * 0.12)
    for test in data.tests:
        _test_table(pdf, test, cols, width)

    if data.pending_tests:
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(
            0,
            5,
            _latin1("Results pending: " + ", ".join(data.pending_tests)),
            new_x="LMARGIN",
            new_y="NEXT",
        )
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(
        0,
        4,
        "Values in bold are outside the reference range. Reference ranges are adult ranges "
        "for the patient's sex and age; interpret results in the clinical context.",
    )
    return RenderedReport(bytes(pdf.output()), pdf.page_no())
