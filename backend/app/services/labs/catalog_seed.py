"""A starter test catalog for an Indian outpatient clinic.

Standard units and common adult reference intervals. Labs differ by method and analyser, so
the clinic must review every range and critical limit before use (see README). Used by
`scripts.seed_lab` for the seed clinic and by the test fixtures.
"""

import uuid
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    LabCategory,
    LabRangeSex,
    LabReferenceRange,
    LabSampleType,
    LabTest,
    LabTestParameter,
    LabValueType,
)
from app.services.labs.catalog import LabTestSpec, ParameterSpec, RangeSpec, decimal_or_none

M, F = LabRangeSex.MALE, LabRangeSex.FEMALE
HAEM, BIO, HORM = LabCategory.HAEMATOLOGY, LabCategory.BIOCHEMISTRY, LabCategory.HORMONES
URINE, SERO = LabCategory.URINE, LabCategory.SEROLOGY
BLOOD = LabSampleType.BLOOD

NIL_GRADES = ("Nil", "Trace", "1+", "2+", "3+", "4+")
NEG_POS = ("Negative", "Positive")
TITRES = ("<1:20", "1:20", "1:40", "1:80", "1:160", "1:320", "1:640")


def r(
    low: float | None,
    high: float | None,
    critical_low: float | None = None,
    critical_high: float | None = None,
    sex: LabRangeSex = LabRangeSex.ANY,
    ages: tuple[int, int] | None = None,
) -> RangeSpec:
    return RangeSpec(
        sex=sex,
        low=low,
        high=high,
        critical_low=critical_low,
        critical_high=critical_high,
        age_min_years=ages[0] if ages else None,
        age_max_years=ages[1] if ages else None,
    )


CHILD = (1, 12)


def num(
    code: str,
    name: str,
    unit: str,
    *ranges: RangeSpec,
    decimals: int = 1,
    delta: float | None = None,
) -> ParameterSpec:
    return ParameterSpec(
        code=code, name=name, unit=unit, ranges=ranges, decimals=decimals, delta_percent=delta
    )


def pick(
    code: str, name: str, choices: tuple[str, ...], normal: str | None = None
) -> ParameterSpec:
    return ParameterSpec(
        code=code,
        name=name,
        value_type=LabValueType.CHOICE,
        choices=choices,
        ranges=(RangeSpec(text_normal=normal),) if normal else (),
    )


def test(
    code: str,
    name: str,
    category: LabCategory,
    container: str,
    hours: int,
    *parameters: ParameterSpec,
    sample: LabSampleType = BLOOD,
) -> LabTestSpec:
    return LabTestSpec(
        code=code,
        name=name,
        category=category,
        sample_type=sample,
        container=container,
        turnaround_hours=hours,
        is_panel=len(parameters) > 1,
        parameters=parameters,
    )


GLUCOSE = (r(70, 100, 40, 450),)

CATALOG: tuple[LabTestSpec, ...] = (
    test(
        "CBC",
        "Complete blood count",
        HAEM,
        "EDTA",
        4,
        num(
            "HB",
            "Haemoglobin",
            "g/dL",
            r(13.0, 17.0, 7.0, 20.0, M),
            r(12.0, 15.0, 7.0, 20.0, F),
            r(11.5, 15.5, 7.0, 20.0, ages=CHILD),
            delta=20,
        ),
        num(
            "TLC",
            "Total leucocyte count",
            "x10^3/uL",
            r(4.0, 11.0, 2.0, 30.0),
            r(4.5, 13.5, 2.0, 30.0, ages=CHILD),
            delta=50,
        ),
        num("NEUT", "Neutrophils", "%", r(40, 75), decimals=0),
        num("LYMPH", "Lymphocytes", "%", r(20, 45), decimals=0),
        num("MONO", "Monocytes", "%", r(2, 10), decimals=0),
        num("EOS", "Eosinophils", "%", r(1, 6), decimals=0),
        num("BASO", "Basophils", "%", r(0, 1), decimals=0),
        num("RBC", "RBC count", "x10^6/uL", r(4.5, 5.5, sex=M), r(3.8, 4.8, sex=F), decimals=2),
        num("PCV", "Haematocrit (PCV)", "%", r(40, 50, sex=M), r(36, 46, sex=F)),
        num("MCV", "MCV", "fL", r(83, 101)),
        num("MCH", "MCH", "pg", r(27, 32)),
        num("MCHC", "MCHC", "g/dL", r(31.5, 34.5)),
        num(
            "PLT",
            "Platelet count",
            "x10^3/uL",
            r(150, 410, 20, 1000),
            r(150, 450, 20, 1000, ages=CHILD),
            decimals=0,
            delta=50,
        ),
    ),
    test(
        "ESR",
        "Erythrocyte sedimentation rate",
        HAEM,
        "Sodium citrate",
        4,
        num("ESR", "ESR", "mm/hr", r(0, 15, sex=M), r(0, 20, sex=F), decimals=0),
    ),
    test(
        "FBS",
        "Fasting blood sugar",
        BIO,
        "Fluoride",
        2,
        num("FBS", "Fasting blood sugar", "mg/dL", *GLUCOSE, decimals=0),
    ),
    test(
        "PPBS",
        "Post-prandial blood sugar",
        BIO,
        "Fluoride",
        2,
        num("PPBS", "Post-prandial blood sugar", "mg/dL", r(70, 140, 40, 450), decimals=0),
    ),
    test(
        "RBS",
        "Random blood sugar",
        BIO,
        "Fluoride",
        2,
        num("RBS", "Random blood sugar", "mg/dL", r(70, 140, 40, 450), decimals=0),
    ),
    test(
        "HBA1C",
        "HbA1c (glycated haemoglobin)",
        BIO,
        "EDTA",
        24,
        num("HBA1C", "HbA1c", "%", r(4.0, 5.6), delta=20),
    ),
    test(
        "LIPID",
        "Lipid profile",
        BIO,
        "Plain (serum)",
        24,
        num("CHOL", "Total cholesterol", "mg/dL", r(None, 200), decimals=0),
        num("TG", "Triglycerides", "mg/dL", r(None, 150, None, 1000), decimals=0),
        num("HDL", "HDL cholesterol", "mg/dL", r(40, None, sex=M), r(50, None, sex=F), decimals=0),
        num("LDL", "LDL cholesterol", "mg/dL", r(None, 100), decimals=0),
        num("VLDL", "VLDL cholesterol", "mg/dL", r(None, 30), decimals=0),
        num("NONHDL", "Non-HDL cholesterol", "mg/dL", r(None, 130), decimals=0),
    ),
    test(
        "LFT",
        "Liver function test",
        BIO,
        "Plain (serum)",
        24,
        num("TBIL", "Total bilirubin", "mg/dL", r(0.3, 1.2, None, 15.0)),
        num("DBIL", "Direct bilirubin", "mg/dL", r(0.0, 0.3), decimals=2),
        num("AST", "SGOT (AST)", "U/L", r(0, 40, None, 1000), decimals=0),
        num("ALT", "SGPT (ALT)", "U/L", r(0, 45, None, 1000), decimals=0),
        num("ALP", "Alkaline phosphatase", "U/L", r(44, 147), decimals=0),
        num("GGT", "Gamma GT", "U/L", r(0, 55), decimals=0),
        num("TP", "Total protein", "g/dL", r(6.0, 8.3)),
        num("ALB", "Albumin", "g/dL", r(3.5, 5.2)),
        num("GLOB", "Globulin", "g/dL", r(2.0, 3.5)),
    ),
    test(
        "KFT",
        "Kidney function test (RFT)",
        BIO,
        "Plain (serum)",
        24,
        num("UREA", "Blood urea", "mg/dL", r(15, 40, None, 200), decimals=0, delta=50),
        num("BUN", "Blood urea nitrogen", "mg/dL", r(7, 20, None, 100), decimals=0),
        num(
            "CREAT",
            "Serum creatinine",
            "mg/dL",
            r(0.7, 1.3, None, 10.0, M),
            r(0.6, 1.1, None, 10.0, F),
            decimals=2,
            delta=30,
        ),
        num("URIC", "Uric acid", "mg/dL", r(3.4, 7.0, sex=M), r(2.4, 6.0, sex=F)),
    ),
    test(
        "ELEC",
        "Serum electrolytes",
        BIO,
        "Plain (serum)",
        6,
        num("NA", "Sodium", "mmol/L", r(135, 145, 120, 160), decimals=0, delta=5),
        num("K", "Potassium", "mmol/L", r(3.5, 5.1, 2.8, 6.2), delta=20),
        num("CL", "Chloride", "mmol/L", r(98, 107, 80, 120), decimals=0),
    ),
    test(
        "THYROID",
        "Thyroid profile (T3, T4, TSH)",
        HORM,
        "Plain (serum)",
        24,
        num("T3", "Total T3", "ng/dL", r(80, 200), decimals=0),
        num("T4", "Total T4", "ug/dL", r(5.1, 14.1)),
        num("TSH", "TSH", "uIU/mL", r(0.4, 4.0, None, 100.0), decimals=2, delta=100),
    ),
    test(
        "TSH",
        "TSH (thyroid stimulating hormone)",
        HORM,
        "Plain (serum)",
        24,
        num("TSH", "TSH", "uIU/mL", r(0.4, 4.0, None, 100.0), decimals=2, delta=100),
    ),
    test(
        "VITD",
        "Vitamin D (25-OH)",
        HORM,
        "Plain (serum)",
        48,
        num("VITD", "25-OH Vitamin D", "ng/mL", r(30, 100, None, 150)),
    ),
    test(
        "B12",
        "Vitamin B12",
        HORM,
        "Plain (serum)",
        48,
        num("B12", "Vitamin B12", "pg/mL", r(211, 911), decimals=0),
    ),
    test(
        "CRP",
        "C-reactive protein (quantitative)",
        SERO,
        "Plain (serum)",
        6,
        num("CRP", "CRP", "mg/L", r(0, 5)),
    ),
    test(
        "URINE",
        "Urine routine and microscopy",
        URINE,
        "Sterile container",
        4,
        pick("COLOUR", "Colour", ("Pale yellow", "Yellow", "Dark yellow", "Red", "Other")),
        pick("APPEAR", "Appearance", ("Clear", "Slightly turbid", "Turbid"), "Clear"),
        num("PH", "pH", "", r(4.5, 8.0)),
        num("SG", "Specific gravity", "", r(1.005, 1.030), decimals=3),
        pick("PROT", "Protein", NIL_GRADES, "Nil"),
        pick("GLU", "Glucose", NIL_GRADES, "Nil"),
        pick("KET", "Ketones", NEG_POS, "Negative"),
        pick("BLD", "Blood", ("Negative", "Trace", "Positive"), "Negative"),
        num("PUS", "Pus cells", "/hpf", r(0, 5), decimals=0),
        num("RBCU", "Red blood cells", "/hpf", r(0, 2), decimals=0),
        num("EPI", "Epithelial cells", "/hpf", r(0, 5), decimals=0),
        sample=LabSampleType.URINE,
    ),
    test(
        "UMALB",
        "Urine microalbumin",
        URINE,
        "Sterile container",
        24,
        num("UMALB", "Urine microalbumin", "mg/L", r(0, 30), decimals=0),
        sample=LabSampleType.URINE,
    ),
    test(
        "WIDAL",
        "Widal test",
        SERO,
        "Plain (serum)",
        6,
        pick("STO", "S. Typhi O", TITRES),
        pick("STH", "S. Typhi H", TITRES),
        pick("SPA", "S. Paratyphi AH", TITRES),
        pick("SPB", "S. Paratyphi BH", TITRES),
        pick("WIDAL", "Interpretation", ("Not significant", "Significant"), "Not significant"),
    ),
    test(
        "NS1",
        "Dengue NS1 antigen",
        SERO,
        "Plain (serum)",
        4,
        pick("NS1", "Dengue NS1 antigen", NEG_POS, "Negative"),
    ),
    test(
        "MPAG",
        "Malaria antigen (Pf/Pv)",
        SERO,
        "EDTA",
        2,
        pick("PF", "P. falciparum antigen", NEG_POS, "Negative"),
        pick("PV", "P. vivax antigen", NEG_POS, "Negative"),
    ),
)


async def install_catalog(session: AsyncSession, clinic_id: UUID) -> int:
    """Add the starter tests the clinic doesn't have yet (matched by code). Commits once.

    Bulk inserts (three statements) rather than the admin path, so seeding a clinic is cheap
    (tests create a catalog per throwaway clinic).
    """
    existing = set(
        (await session.scalars(select(LabTest.code).where(LabTest.clinic_id == clinic_id))).all()
    )
    tests: list[dict[str, object]] = []
    params: list[dict[str, object]] = []
    ranges: list[dict[str, object]] = []
    for order, spec in enumerate(CATALOG):
        if spec.code in existing:
            continue
        test_id = uuid.uuid4()
        tests.append(
            {
                "id": test_id,
                "clinic_id": clinic_id,
                "code": spec.code,
                "name": spec.name,
                "category": spec.category,
                "sample_type": spec.sample_type,
                "container": spec.container,
                "turnaround_hours": spec.turnaround_hours,
                "is_panel": spec.is_panel,
                "sort_order": order * 10,
            }
        )
        for position, p in enumerate(spec.parameters):
            param_id = uuid.uuid4()
            params.append(
                {
                    "id": param_id,
                    "test_id": test_id,
                    "code": p.code,
                    "name": p.name,
                    "unit": p.unit or None,
                    "value_type": p.value_type,
                    "choices": list(p.choices),
                    "decimals": p.decimals,
                    "delta_percent": decimal_or_none(p.delta_percent),
                    "sort_order": position,
                }
            )
            ranges.extend(
                {
                    "parameter_id": param_id,
                    "sex": r.sex,
                    "age_min_years": r.age_min_years,
                    "age_max_years": r.age_max_years,
                    "low": decimal_or_none(r.low),
                    "high": decimal_or_none(r.high),
                    "critical_low": decimal_or_none(r.critical_low),
                    "critical_high": decimal_or_none(r.critical_high),
                    "text_normal": r.text_normal,
                }
                for r in p.ranges
            )
    if tests:
        await session.execute(insert(LabTest), tests)
        await session.execute(insert(LabTestParameter), params)
        if ranges:
            await session.execute(insert(LabReferenceRange), ranges)
        await session.commit()
    return len(tests)
