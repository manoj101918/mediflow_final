"""Lab test catalog: tests, their parameters and reference ranges (managed by admin).

Results snapshot the parameter name, unit and range when they are entered, so editing or
deactivating anything here only affects future results. Parameters are never deleted (results
reference them); leaving one out of an update deactivates it. Ranges are replaced wholesale.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Clinic,
    LabCategory,
    LabRangeSex,
    LabReferenceRange,
    LabSampleType,
    LabTest,
    LabTestParameter,
    LabValueType,
)
from app.services.booking.dberrors import booking_error_for
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success


@dataclass(frozen=True)
class RangeSpec:
    sex: LabRangeSex = LabRangeSex.ANY
    age_min_years: int | None = None
    age_max_years: int | None = None
    low: float | None = None
    high: float | None = None
    critical_low: float | None = None
    critical_high: float | None = None
    text_normal: str | None = None


@dataclass(frozen=True)
class ParameterSpec:
    code: str
    name: str
    unit: str | None = None
    value_type: LabValueType = LabValueType.NUMERIC
    choices: Sequence[str] = ()
    decimals: int = 1
    delta_percent: float | None = None
    is_active: bool = True
    ranges: Sequence[RangeSpec] = ()
    id: UUID | None = None


@dataclass(frozen=True)
class LabTestSpec:
    code: str
    name: str
    category: LabCategory
    sample_type: LabSampleType
    parameters: Sequence[ParameterSpec]
    container: str | None = None
    turnaround_hours: int = 24
    is_panel: bool = False
    is_active: bool = True
    sort_order: int = 0


@dataclass
class CatalogParameter:
    parameter: LabTestParameter
    ranges: list[LabReferenceRange] = field(default_factory=list)


@dataclass
class CatalogTest:
    test: LabTest
    parameters: list[CatalogParameter] = field(default_factory=list)


def decimal_or_none(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _range_row(parameter_id: UUID, spec: RangeSpec) -> LabReferenceRange:
    return LabReferenceRange(
        parameter_id=parameter_id,
        sex=spec.sex,
        age_min_years=spec.age_min_years,
        age_max_years=spec.age_max_years,
        low=decimal_or_none(spec.low),
        high=decimal_or_none(spec.high),
        critical_low=decimal_or_none(spec.critical_low),
        critical_high=decimal_or_none(spec.critical_high),
        text_normal=spec.text_normal,
    )


async def load_catalog(
    session: AsyncSession,
    clinic_id: UUID,
    *,
    test_ids: Sequence[UUID] | None = None,
    active_only: bool = False,
) -> list[CatalogTest]:
    """Tests with their parameters and ranges, in display order."""
    query = select(LabTest).where(LabTest.clinic_id == clinic_id)
    if test_ids is not None:
        query = query.where(LabTest.id.in_(test_ids))
    if active_only:
        query = query.where(LabTest.is_active)
    tests = list((await session.scalars(query.order_by(LabTest.sort_order, LabTest.name))).all())
    if not tests:
        return []
    by_test = {t.id: CatalogTest(t) for t in tests}

    param_query = select(LabTestParameter).where(LabTestParameter.test_id.in_(by_test))
    if active_only:
        param_query = param_query.where(LabTestParameter.is_active)
    params = (
        await session.scalars(
            param_query.order_by(LabTestParameter.sort_order, LabTestParameter.name)
        )
    ).all()
    by_param = {p.id: CatalogParameter(p) for p in params}
    for p in params:
        by_test[p.test_id].parameters.append(by_param[p.id])

    if by_param:
        ranges = (
            await session.scalars(
                select(LabReferenceRange)
                .where(LabReferenceRange.parameter_id.in_(by_param))
                .order_by(
                    LabReferenceRange.sex,
                    LabReferenceRange.age_min_years.nulls_first(),
                    LabReferenceRange.created_at,
                )
            )
        ).all()
        for r in ranges:
            by_param[r.parameter_id].ranges.append(r)
    return list(by_test.values())


async def get_test(session: AsyncSession, clinic_id: UUID, test_id: UUID) -> CatalogTest | None:
    found = await load_catalog(session, clinic_id, test_ids=[test_id])
    return found[0] if found else None


async def _loaded(
    session: AsyncSession, clinic_id: UUID, test_id: UUID
) -> BookingResult[CatalogTest]:
    found = await get_test(session, clinic_id, test_id)
    if found is None:
        return failure(BookingErrorCode.NOT_FOUND, "Lab test not found.")
    return success(found)


async def _write_parameters(
    session: AsyncSession, test_id: UUID, specs: Sequence[ParameterSpec]
) -> BookingResult[None]:
    existing = {
        p.id: p
        for p in (
            await session.scalars(
                select(LabTestParameter).where(LabTestParameter.test_id == test_id)
            )
        ).all()
    }
    kept: set[UUID] = set()
    for order, spec in enumerate(specs):
        values = {
            "code": spec.code,
            "name": spec.name,
            "unit": spec.unit or None,
            "value_type": spec.value_type,
            "choices": list(spec.choices),
            "decimals": spec.decimals,
            "delta_percent": decimal_or_none(spec.delta_percent),
            "is_active": spec.is_active,
            "sort_order": order,
        }
        if spec.id is not None:
            param = existing.get(spec.id)
            if param is None:
                return failure(BookingErrorCode.VALIDATION, "Unknown parameter for this test.")
            for key, value in values.items():
                setattr(param, key, value)
        else:
            # Re-adding a code that was left out earlier revives that parameter.
            param = next((p for p in existing.values() if p.code == spec.code), None)
            if param is not None and param.id not in kept:
                for key, value in values.items():
                    setattr(param, key, value)
            else:
                param = LabTestParameter(test_id=test_id, **values)
                session.add(param)
        await session.flush()
        kept.add(param.id)
        await session.execute(
            delete(LabReferenceRange).where(LabReferenceRange.parameter_id == param.id)
        )
        session.add_all(_range_row(param.id, r) for r in spec.ranges)

    dropped = [pid for pid in existing if pid not in kept]
    if dropped:
        await session.execute(
            update(LabTestParameter).where(LabTestParameter.id.in_(dropped)).values(is_active=False)
        )
    await session.flush()
    return success(None)


_DUPLICATE_CODE = "A test with that code already exists."


async def create_test(
    session: AsyncSession, clinic_id: UUID, spec: LabTestSpec
) -> BookingResult[CatalogTest]:
    try:
        test = LabTest(
            clinic_id=clinic_id,
            code=spec.code,
            name=spec.name,
            category=spec.category,
            sample_type=spec.sample_type,
            container=spec.container,
            turnaround_hours=spec.turnaround_hours,
            is_panel=spec.is_panel,
            is_active=spec.is_active,
            sort_order=spec.sort_order,
        )
        session.add(test)
        await session.flush()
        written = await _write_parameters(session, test.id, spec.parameters)
        if not written.ok:
            await session.rollback()
            return failure(written.code or BookingErrorCode.VALIDATION, written.message)
        await session.commit()
    except DBAPIError as exc:
        await session.rollback()
        code = booking_error_for(exc)
        if code is None:
            raise
        return failure(code, _DUPLICATE_CODE)
    return await _loaded(session, clinic_id, test.id)


async def update_test(
    session: AsyncSession, clinic_id: UUID, test_id: UUID, spec: LabTestSpec
) -> BookingResult[CatalogTest]:
    test = await session.scalar(
        select(LabTest).where(LabTest.id == test_id, LabTest.clinic_id == clinic_id)
    )
    if test is None:
        return failure(BookingErrorCode.NOT_FOUND, "Lab test not found.")
    try:
        test.code = spec.code
        test.name = spec.name
        test.category = spec.category
        test.sample_type = spec.sample_type
        test.container = spec.container
        test.turnaround_hours = spec.turnaround_hours
        test.is_panel = spec.is_panel
        test.is_active = spec.is_active
        test.sort_order = spec.sort_order
        await session.flush()
        written = await _write_parameters(session, test_id, spec.parameters)
        if not written.ok:
            await session.rollback()
            return failure(written.code or BookingErrorCode.VALIDATION, written.message)
        await session.commit()
    except DBAPIError as exc:
        await session.rollback()
        code = booking_error_for(exc)
        if code is None:
            raise
        return failure(code, _DUPLICATE_CODE)
    return await _loaded(session, clinic_id, test_id)


async def set_test_active(
    session: AsyncSession, clinic_id: UUID, test_id: UUID, active: bool
) -> BookingResult[CatalogTest]:
    result = await session.execute(
        update(LabTest)
        .where(LabTest.id == test_id, LabTest.clinic_id == clinic_id)
        .values(is_active=active)
    )
    if getattr(result, "rowcount", 0) == 0:
        await session.rollback()
        return failure(BookingErrorCode.NOT_FOUND, "Lab test not found.")
    await session.commit()
    return await _loaded(session, clinic_id, test_id)


async def requires_verification(session: AsyncSession, clinic_id: UUID) -> bool:
    value = await session.scalar(
        select(Clinic.lab_requires_verification).where(Clinic.id == clinic_id)
    )
    return True if value is None else value


async def set_requires_verification(session: AsyncSession, clinic_id: UUID, value: bool) -> bool:
    await session.execute(
        update(Clinic).where(Clinic.id == clinic_id).values(lab_requires_verification=value)
    )
    await session.commit()
    return value
