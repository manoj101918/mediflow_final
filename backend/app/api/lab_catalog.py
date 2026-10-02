"""Lab catalog conversions shared by the admin and lab routers."""

from decimal import Decimal

from app.db.models import LabReferenceRange
from app.schemas.labs import LabTestIn, LabTestOut, ParameterOut, ReferenceRangeOut
from app.services.labs.catalog import CatalogTest, LabTestSpec, ParameterSpec, RangeSpec


def _float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def range_out(row: LabReferenceRange) -> ReferenceRangeOut:
    return ReferenceRangeOut(
        id=row.id,
        sex=row.sex,
        age_min_years=row.age_min_years,
        age_max_years=row.age_max_years,
        low=_float(row.low),
        high=_float(row.high),
        critical_low=_float(row.critical_low),
        critical_high=_float(row.critical_high),
        text_normal=row.text_normal,
    )


def lab_test_out(item: CatalogTest) -> LabTestOut:
    t = item.test
    return LabTestOut(
        id=t.id,
        code=t.code,
        name=t.name,
        category=t.category,
        sample_type=t.sample_type,
        container=t.container,
        turnaround_hours=t.turnaround_hours,
        is_panel=t.is_panel,
        is_active=t.is_active,
        sort_order=t.sort_order,
        updated_at=t.updated_at,
        parameters=[
            ParameterOut(
                id=p.parameter.id,
                code=p.parameter.code,
                name=p.parameter.name,
                unit=p.parameter.unit,
                value_type=p.parameter.value_type,
                choices=list(p.parameter.choices),
                decimals=p.parameter.decimals,
                delta_percent=_float(p.parameter.delta_percent),
                is_active=p.parameter.is_active,
                ranges=[range_out(r) for r in p.ranges],
            )
            for p in item.parameters
        ],
    )


def lab_test_spec(body: LabTestIn) -> LabTestSpec:
    return LabTestSpec(
        code=body.code,
        name=body.name,
        category=body.category,
        sample_type=body.sample_type,
        container=body.container,
        turnaround_hours=body.turnaround_hours,
        is_panel=body.is_panel,
        is_active=body.is_active,
        sort_order=body.sort_order,
        parameters=[
            ParameterSpec(
                **p.model_dump(exclude={"ranges"}),
                ranges=[RangeSpec(**r.model_dump()) for r in p.ranges],
            )
            for p in body.parameters
        ],
    )
