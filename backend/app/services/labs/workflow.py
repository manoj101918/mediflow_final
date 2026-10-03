"""The lab's work on an order: collect, reject, enter results, submit, verify, release, amend.

Every function locks the order row first (then the item), changes statuses through
`transitions`, records events, re-derives the order status and commits once. Releasing
(`_release`) does everything the doctor-facing side depends on in the same transaction:
statuses and timestamps, critical alerts, the generated report row and the ingestion job
that renders the PDF and indexes the results.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    IngestionStatus,
    LabCriticalAlert,
    LabItemStatus,
    LabOrder,
    LabOrderItem,
    LabReferenceRange,
    LabResult,
    LabSample,
    LabTest,
    LabTestParameter,
    LabValueType,
    Patient,
    PatientReport,
    RecordSourceType,
    ReportType,
)
from app.services.booking.actor import StaffActor
from app.services.booking.dberrors import booking_error_for
from app.services.booking.results import BookingErrorCode, BookingResult, failure, success
from app.services.booking.timeutil import local_date, utcnow
from app.services.ingestion.jobs import enqueue
from app.services.labs.common import (
    ORDER_NOT_FOUND,
    ClinicLabSettings,
    add_event,
    clinic_settings,
    lab_check,
    load_order,
    lock_item,
    move,
    order_items,
    refresh_order,
)
from app.services.labs.numbers import next_sample_code
from app.services.labs.ranges import (
    CRITICAL_FLAGS,
    age_on,
    flag_numeric,
    flag_text,
    range_label,
    select_range,
)
from app.services.labs.transitions import LabAction, allowed_sources, role_allowed

LOCKED = "Released results cannot be edited. Use an amendment."


@dataclass(frozen=True)
class ResultValue:
    parameter_id: UUID
    # Numbers for numeric parameters, the chosen/typed text otherwise; None clears a draft.
    value: str | float | None


def _not_allowed(action: LabAction) -> BookingResult[LabOrder]:
    messages = {
        LabAction.VERIFY: "Only a lab supervisor can verify results.",
        LabAction.SEND_BACK: "Only a lab supervisor can send results back.",
        LabAction.RELEASE: "Results must be verified by a lab supervisor before release.",
        LabAction.AMEND: "Only a lab supervisor can amend released results.",
    }
    return failure(BookingErrorCode.FORBIDDEN, messages.get(action, "Not allowed."))


def _wrong_state(action: LabAction, status: LabItemStatus) -> BookingResult[LabOrder]:
    pretty = status.value.replace("_", " ")
    return failure(
        BookingErrorCode.INVALID_TRANSITION, f"Cannot {action.value.replace('_', ' ')}: {pretty}."
    )


async def _finish(
    session: AsyncSession, result: BookingResult[LabOrder]
) -> BookingResult[LabOrder]:
    if not result.ok:
        await session.rollback()
        return result
    try:
        await session.commit()
    except DBAPIError as exc:
        await session.rollback()
        code = booking_error_for(exc)
        if code is None:
            raise
        return failure(code, LOCKED if code is BookingErrorCode.RECORD_LOCKED else "")
    return result


async def _guarded(
    session: AsyncSession, actor: StaffActor, action: LabAction
) -> BookingResult[ClinicLabSettings]:
    checked = lab_check(actor)
    if not checked.ok:
        return failure(checked.code or BookingErrorCode.FORBIDDEN, checked.message)
    settings = await clinic_settings(session, actor.clinic_id)
    if not role_allowed(action, actor.role, settings.requires_verification):
        return failure(BookingErrorCode.FORBIDDEN, _not_allowed(action).message)
    return success(settings)


# ---------------------------------------------------------------------------
# Collection and rejection
# ---------------------------------------------------------------------------


async def collect(
    session: AsyncSession, actor: StaffActor, order_id: UUID, item_ids: Sequence[UUID]
) -> BookingResult[LabOrder]:
    """Collect samples for the chosen tests: one tube per sample type and container."""
    return await _finish(session, await _collect(session, actor, order_id, item_ids))


async def _collect(
    session: AsyncSession, actor: StaffActor, order_id: UUID, item_ids: Sequence[UUID]
) -> BookingResult[LabOrder]:
    guarded = await _guarded(session, actor, LabAction.COLLECT)
    if not guarded.ok:
        return failure(guarded.code or BookingErrorCode.FORBIDDEN, guarded.message)
    settings = guarded.unwrap()
    order = await load_order(session, actor.clinic_id, order_id, lock=True)
    if order is None:
        return failure(BookingErrorCode.NOT_FOUND, ORDER_NOT_FOUND)
    items = {i.id: i for i in await order_items(session, order.id)}
    wanted = list(dict.fromkeys(item_ids))
    if not wanted or any(i not in items for i in wanted):
        return failure(BookingErrorCode.VALIDATION, "Choose the tests being collected.")
    sources = allowed_sources(LabAction.COLLECT, settings.requires_verification)
    for item_id in wanted:
        if items[item_id].status not in sources:
            return _wrong_state(LabAction.COLLECT, items[item_id].status)

    tests = {
        t.id: t
        for t in (
            await session.scalars(
                select(LabTest).where(LabTest.id.in_({items[i].test_id for i in wanted}))
            )
        ).all()
    }
    day = local_date(utcnow(), settings.tz)
    tubes: dict[tuple[str, str], LabSample] = {}
    for item_id in wanted:
        item = items[item_id]
        test = tests[item.test_id]
        key = (test.sample_type.value, test.container or "")
        sample = tubes.get(key)
        if sample is None:
            sample = LabSample(
                clinic_id=order.clinic_id,
                order_id=order.id,
                sample_code=await next_sample_code(session, order.clinic_id, day),
                sample_type=test.sample_type,
                container=test.container,
                collected_by=actor.user_id,
            )
            session.add(sample)
            await session.flush()
            tubes[key] = sample
        event = "recollected" if item.status == LabItemStatus.SAMPLE_REJECTED else "collected"
        item.sample_id = sample.id
        item.rejection_reason = None
        move(session, order, item, LabItemStatus.SAMPLE_COLLECTED, event, actor.user_id)
    await refresh_order(session, order)
    return success(order)


async def reject_sample(
    session: AsyncSession, actor: StaffActor, sample_id: UUID, reason: str
) -> BookingResult[LabOrder]:
    """Reject a tube (haemolysed, insufficient, wrong container): its tests need recollection."""
    return await _finish(session, await _reject(session, actor, sample_id, reason))


async def _reject(
    session: AsyncSession, actor: StaffActor, sample_id: UUID, reason: str
) -> BookingResult[LabOrder]:
    guarded = await _guarded(session, actor, LabAction.REJECT)
    if not guarded.ok:
        return failure(guarded.code or BookingErrorCode.FORBIDDEN, guarded.message)
    if not reason.strip():
        return failure(BookingErrorCode.VALIDATION, "Give a reason for rejecting the sample.")
    order_id = await session.scalar(
        select(LabSample.order_id).where(
            LabSample.id == sample_id, LabSample.clinic_id == actor.clinic_id
        )
    )
    order = await load_order(session, actor.clinic_id, order_id, lock=True) if order_id else None
    sample = await session.get(LabSample, sample_id) if order else None
    if order is None or sample is None:
        return failure(BookingErrorCode.NOT_FOUND, "Sample not found.")
    if sample.rejected_at is not None:
        return failure(BookingErrorCode.INVALID_TRANSITION, "This sample was already rejected.")
    items = [i for i in await order_items(session, order.id) if i.sample_id == sample.id]
    targets = [i for i in items if i.status == LabItemStatus.SAMPLE_COLLECTED]
    if not targets:
        return failure(
            BookingErrorCode.INVALID_TRANSITION,
            "Only samples whose results have not been submitted can be rejected.",
        )
    sample.rejected_at = utcnow()
    sample.rejected_by = actor.user_id
    sample.rejected_reason = reason.strip()
    for item in targets:
        # Draft values belonged to the rejected tube.
        await session.execute(delete(LabResult).where(LabResult.order_item_id == item.id))
        item.rejection_reason = reason.strip()
        move(session, order, item, LabItemStatus.SAMPLE_REJECTED, "rejected", actor.user_id)
    await refresh_order(session, order)
    return success(order)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComputedValue:
    parameter: LabTestParameter
    numeric: Decimal | None
    text: str | None
    reference: LabReferenceRange | None


def parse_value(parameter: LabTestParameter, raw: str | float) -> tuple[Decimal | None, str | None]:
    if parameter.value_type == LabValueType.NUMERIC:
        try:
            number = Decimal(str(raw).strip())
        except InvalidOperation:
            raise ValueError(f"{parameter.name} must be a number.") from None
        if not number.is_finite() or abs(number) >= Decimal(10) ** 9:
            raise ValueError(f"{parameter.name} must be a number.")
        # Stored (and reported) at the parameter's precision: 118.0 -> 118, 6.94 -> 6.9.
        return number.quantize(Decimal(1).scaleb(-parameter.decimals), ROUND_HALF_UP), None
    text = str(raw).strip()
    if not text or len(text) > 500:
        raise ValueError(f"{parameter.name} needs a value.")
    if parameter.value_type == LabValueType.CHOICE:
        match = next((c for c in parameter.choices if c.casefold() == text.casefold()), None)
        if match is None:
            raise ValueError(f"{parameter.name}: choose one of {', '.join(parameter.choices)}.")
        text = match
    return None, text


async def patient_age_sex(
    session: AsyncSession, order: LabOrder, item: LabOrderItem, settings: ClinicLabSettings
) -> tuple[Patient, int | None]:
    patient = await session.get(Patient, order.patient_id)
    assert patient is not None  # noqa: S101 - FK guarantees it
    collected_at = None
    if item.sample_id is not None:
        collected_at = await session.scalar(
            select(LabSample.collected_at).where(LabSample.id == item.sample_id)
        )
    day = local_date(collected_at or utcnow(), settings.tz)
    return patient, age_on(day, patient.date_of_birth, patient.age_years)


async def _ranges_by_parameter(
    session: AsyncSession, parameter_ids: Sequence[UUID]
) -> dict[UUID, list[LabReferenceRange]]:
    rows = (
        await session.scalars(
            select(LabReferenceRange).where(LabReferenceRange.parameter_id.in_(parameter_ids))
        )
    ).all()
    out: dict[UUID, list[LabReferenceRange]] = {}
    for r in rows:
        out.setdefault(r.parameter_id, []).append(r)
    return out


def snapshot_result(result: LabResult, c: ComputedValue) -> None:
    """Copy name, unit and the range used onto the result; compute its flag."""
    p, r = c.parameter, c.reference
    result.parameter_code = p.code
    result.parameter_name = p.name
    result.unit = p.unit
    result.value_type = p.value_type
    result.value_numeric = c.numeric
    result.value_text = c.text
    result.ref_low = r.low if r else None
    result.ref_high = r.high if r else None
    result.ref_critical_low = r.critical_low if r else None
    result.ref_critical_high = r.critical_high if r else None
    result.ref_text_normal = r.text_normal if r else None
    result.range_label = range_label(r)
    result.flag = (
        flag_numeric(c.numeric, r) if c.numeric is not None else flag_text(c.text or "", r)
    )
    result.sort_order = p.sort_order


async def _compute(
    session: AsyncSession,
    order: LabOrder,
    item: LabOrderItem,
    values: Sequence[ResultValue],
    settings: ClinicLabSettings,
) -> BookingResult[list[tuple[LabTestParameter, ComputedValue | None]]]:
    parameters = {
        p.id: p
        for p in (
            await session.scalars(
                select(LabTestParameter).where(LabTestParameter.test_id == item.test_id)
            )
        ).all()
    }
    if not values:
        return failure(BookingErrorCode.VALIDATION, "Enter at least one value.")
    if any(v.parameter_id not in parameters for v in values):
        return failure(BookingErrorCode.VALIDATION, "Unknown parameter for this test.")
    patient, age = await patient_age_sex(session, order, item, settings)
    ranges = await _ranges_by_parameter(session, [v.parameter_id for v in values])
    computed: list[tuple[LabTestParameter, ComputedValue | None]] = []
    for v in values:
        parameter = parameters[v.parameter_id]
        if v.value is None or (isinstance(v.value, str) and not v.value.strip()):
            computed.append((parameter, None))
            continue
        try:
            numeric, text = parse_value(parameter, v.value)
        except ValueError as exc:
            return failure(BookingErrorCode.VALIDATION, str(exc))
        reference = select_range(ranges.get(parameter.id, []), patient.gender, age)
        computed.append((parameter, ComputedValue(parameter, numeric, text, reference)))
    return success(computed)


def _critical_names(computed: Sequence[tuple[LabTestParameter, ComputedValue | None]]) -> list[str]:
    names = []
    for parameter, c in computed:
        if c is None or c.numeric is None:
            continue
        probe = LabResult()
        snapshot_result(probe, c)
        if probe.flag in CRITICAL_FLAGS:
            names.append(parameter.name)
    return names


async def save_results(
    session: AsyncSession,
    actor: StaffActor,
    item_id: UUID,
    values: Sequence[ResultValue],
    *,
    confirm_critical: bool = False,
) -> BookingResult[LabOrder]:
    """Save draft values for a collected test (re-saving replaces them)."""
    return await _finish(session, await _save(session, actor, item_id, values, confirm_critical))


async def _save(
    session: AsyncSession,
    actor: StaffActor,
    item_id: UUID,
    values: Sequence[ResultValue],
    confirm_critical: bool,
) -> BookingResult[LabOrder]:
    guarded = await _guarded(session, actor, LabAction.SAVE_RESULTS)
    if not guarded.ok:
        return failure(guarded.code or BookingErrorCode.FORBIDDEN, guarded.message)
    settings = guarded.unwrap()
    locked = await lock_item(session, actor.clinic_id, item_id)
    if not locked.ok:
        return failure(locked.code or BookingErrorCode.NOT_FOUND, locked.message)
    order, item = locked.unwrap().order, locked.unwrap().item
    if item.status == LabItemStatus.RELEASED:
        return failure(BookingErrorCode.RECORD_LOCKED, LOCKED)
    if item.status not in allowed_sources(LabAction.SAVE_RESULTS, settings.requires_verification):
        return _wrong_state(LabAction.SAVE_RESULTS, item.status)

    computed = await _compute(session, order, item, values, settings)
    if not computed.ok:
        return failure(computed.code or BookingErrorCode.VALIDATION, computed.message)
    rows = computed.unwrap()
    critical = _critical_names(rows)
    if critical and not confirm_critical:
        return failure(
            BookingErrorCode.VALIDATION,
            f"Confirm the critical value(s) before saving: {', '.join(critical)}.",
        )

    existing = {
        r.parameter_id: r
        for r in (
            await session.scalars(
                select(LabResult).where(LabResult.order_item_id == item.id, LabResult.is_current)
            )
        ).all()
    }
    for parameter, c in rows:
        current = existing.get(parameter.id)
        if c is None:
            if current is not None:
                await session.delete(current)
            continue
        if current is None:
            current = LabResult(order_item_id=item.id, parameter_id=parameter.id)
            session.add(current)
        snapshot_result(current, c)
        current.entered_by = actor.user_id
        current.entered_at = utcnow()
    add_event(session, order, "results_saved", actor.user_id, item=item)
    await refresh_order(session, order)
    return success(order)


async def _has_results(session: AsyncSession, item_id: UUID) -> bool:
    count = await session.scalar(
        select(func.count())
        .select_from(LabResult)
        .where(LabResult.order_item_id == item_id, LabResult.is_current)
    )
    return bool(count)


async def submit(
    session: AsyncSession, actor: StaffActor, item_id: UUID
) -> BookingResult[LabOrder]:
    """Results are complete: ready for verification (or release, with verification off)."""
    return await _finish(session, await _submit(session, actor, item_id))


async def _submit(
    session: AsyncSession, actor: StaffActor, item_id: UUID
) -> BookingResult[LabOrder]:
    guarded = await _guarded(session, actor, LabAction.SUBMIT)
    if not guarded.ok:
        return failure(guarded.code or BookingErrorCode.FORBIDDEN, guarded.message)
    locked = await lock_item(session, actor.clinic_id, item_id)
    if not locked.ok:
        return failure(locked.code or BookingErrorCode.NOT_FOUND, locked.message)
    order, item = locked.unwrap().order, locked.unwrap().item
    if item.status not in allowed_sources(LabAction.SUBMIT, guarded.unwrap().requires_verification):
        return _wrong_state(LabAction.SUBMIT, item.status)
    if not await _has_results(session, item.id):
        return failure(BookingErrorCode.VALIDATION, "Enter the results before submitting.")
    item.entered_by = actor.user_id
    item.entered_at = utcnow()
    item.return_comment = None
    move(session, order, item, LabItemStatus.RESULT_ENTERED, "submitted", actor.user_id)
    await refresh_order(session, order)
    return success(order)


async def send_back(
    session: AsyncSession, actor: StaffActor, item_id: UUID, comment: str
) -> BookingResult[LabOrder]:
    """Supervisor returns submitted results to the technician (values are kept)."""
    return await _finish(session, await _send_back(session, actor, item_id, comment))


async def _send_back(
    session: AsyncSession, actor: StaffActor, item_id: UUID, comment: str
) -> BookingResult[LabOrder]:
    guarded = await _guarded(session, actor, LabAction.SEND_BACK)
    if not guarded.ok:
        return failure(guarded.code or BookingErrorCode.FORBIDDEN, guarded.message)
    if not comment.strip():
        return failure(BookingErrorCode.VALIDATION, "Say what needs to be checked.")
    locked = await lock_item(session, actor.clinic_id, item_id)
    if not locked.ok:
        return failure(locked.code or BookingErrorCode.NOT_FOUND, locked.message)
    order, item = locked.unwrap().order, locked.unwrap().item
    if item.status not in allowed_sources(
        LabAction.SEND_BACK, guarded.unwrap().requires_verification
    ):
        return _wrong_state(LabAction.SEND_BACK, item.status)
    item.return_comment = comment.strip()
    item.verified_by = None
    item.verified_at = None
    move(session, order, item, LabItemStatus.SAMPLE_COLLECTED, "sent_back", actor.user_id)
    await refresh_order(session, order)
    return success(order)


# ---------------------------------------------------------------------------
# Verification, release, amendment
# ---------------------------------------------------------------------------


async def ensure_generated_report(
    session: AsyncSession, order: LabOrder, actor_id: UUID | None, settings: ClinicLabSettings
) -> PatientReport:
    """The order's generated report row; the PDF itself is rendered by the ingestion job."""
    report = await session.scalar(
        select(PatientReport).where(
            PatientReport.lab_order_id == order.id, PatientReport.is_generated
        )
    )
    if report is None:
        report_id = uuid.uuid4()
        report = PatientReport(
            id=report_id,
            clinic_id=order.clinic_id,
            patient_id=order.patient_id,
            consultation_id=order.consultation_id,
            uploaded_by=actor_id,
            title=f"Lab report {order.order_number}",
            report_type=ReportType.LAB,
            report_date=local_date(utcnow(), settings.tz),
            storage_path=f"{order.clinic_id}/{order.patient_id}/{report_id}.pdf",
            mime_type="application/pdf",
            size_bytes=0,
            lab_order_id=order.id,
            is_generated=True,
        )
        session.add(report)
    else:
        report.ingestion_status = IngestionStatus.PENDING
        report.ingestion_error = None
        report.report_date = local_date(utcnow(), settings.tz)
    await session.flush()
    return report


async def _alert_criticals(session: AsyncSession, order: LabOrder, item: LabOrderItem) -> int:
    criticals = (
        await session.scalars(
            select(LabResult).where(
                LabResult.order_item_id == item.id,
                LabResult.is_current,
                LabResult.flag.in_(CRITICAL_FLAGS),
            )
        )
    ).all()
    already = set(
        (
            await session.scalars(
                select(LabCriticalAlert.result_id).where(
                    LabCriticalAlert.result_id.in_([r.id for r in criticals])
                )
            )
        ).all()
    )
    for result in criticals:
        if result.id in already:
            continue
        session.add(
            LabCriticalAlert(
                clinic_id=order.clinic_id,
                result_id=result.id,
                order_id=order.id,
                patient_id=order.patient_id,
                doctor_id=order.ordering_doctor_id,
            )
        )
    return len(criticals) - len(already)


async def release_in_session(
    session: AsyncSession,
    order: LabOrder,
    items: Sequence[LabOrderItem],
    actor_id: UUID | None,
    settings: ClinicLabSettings,
) -> None:
    """Release items without committing: statuses, alerts, report row, ingestion job, events."""
    for item in items:
        item.released_at = utcnow()
        item.released_by = actor_id
        move(session, order, item, LabItemStatus.RELEASED, "released", actor_id)
        await session.flush()
        await _alert_criticals(session, order, item)
    await ensure_generated_report(session, order, actor_id, settings)
    await enqueue(session, order.clinic_id, order.patient_id, RecordSourceType.LAB_RESULT, order.id)
    # New results go back into the ordering doctor's inbox.
    order.reviewed_at = None
    order.reviewed_by = None
    # Hook for notifying the patient later (WhatsApp/SMS); nothing consumes it yet.
    add_event(session, order, "lab_report_released", actor_id)
    await refresh_order(session, order)


async def verify(
    session: AsyncSession, actor: StaffActor, item_id: UUID
) -> BookingResult[LabOrder]:
    """Supervisor verifies submitted results and releases them to the doctor."""
    return await _finish(session, await _verify(session, actor, item_id))


async def _verify(
    session: AsyncSession, actor: StaffActor, item_id: UUID
) -> BookingResult[LabOrder]:
    guarded = await _guarded(session, actor, LabAction.VERIFY)
    if not guarded.ok:
        return failure(guarded.code or BookingErrorCode.FORBIDDEN, guarded.message)
    settings = guarded.unwrap()
    locked = await lock_item(session, actor.clinic_id, item_id)
    if not locked.ok:
        return failure(locked.code or BookingErrorCode.NOT_FOUND, locked.message)
    order, item = locked.unwrap().order, locked.unwrap().item
    if item.status not in allowed_sources(LabAction.VERIFY, settings.requires_verification):
        return _wrong_state(LabAction.VERIFY, item.status)
    item.verified_by = actor.user_id
    item.verified_at = utcnow()
    move(session, order, item, LabItemStatus.VERIFIED, "verified", actor.user_id)
    await release_in_session(session, order, [item], actor.user_id, settings)
    return success(order)


async def release(
    session: AsyncSession, actor: StaffActor, item_id: UUID
) -> BookingResult[LabOrder]:
    """Release one test's results (verified ones, or submitted ones when verification is off)."""
    return await _finish(session, await _release(session, actor, item_id))


async def _release(
    session: AsyncSession, actor: StaffActor, item_id: UUID
) -> BookingResult[LabOrder]:
    guarded = await _guarded(session, actor, LabAction.RELEASE)
    if not guarded.ok:
        return failure(guarded.code or BookingErrorCode.FORBIDDEN, guarded.message)
    settings = guarded.unwrap()
    locked = await lock_item(session, actor.clinic_id, item_id)
    if not locked.ok:
        return failure(locked.code or BookingErrorCode.NOT_FOUND, locked.message)
    order, item = locked.unwrap().order, locked.unwrap().item
    if item.status not in allowed_sources(LabAction.RELEASE, settings.requires_verification):
        if item.status == LabItemStatus.RESULT_ENTERED:
            return failure(
                BookingErrorCode.INVALID_TRANSITION,
                "These results must be verified by a lab supervisor before release.",
            )
        return _wrong_state(LabAction.RELEASE, item.status)
    await release_in_session(session, order, [item], actor.user_id, settings)
    return success(order)


async def amend(
    session: AsyncSession,
    actor: StaffActor,
    item_id: UUID,
    values: Sequence[ResultValue],
    reason: str,
) -> BookingResult[LabOrder]:
    """Correct released results: new versions with a reason; the old ones stay in history."""
    return await _finish(session, await _amend(session, actor, item_id, values, reason))


async def _amend(
    session: AsyncSession,
    actor: StaffActor,
    item_id: UUID,
    values: Sequence[ResultValue],
    reason: str,
) -> BookingResult[LabOrder]:
    guarded = await _guarded(session, actor, LabAction.AMEND)
    if not guarded.ok:
        return failure(guarded.code or BookingErrorCode.FORBIDDEN, guarded.message)
    settings = guarded.unwrap()
    if not reason.strip():
        return failure(BookingErrorCode.VALIDATION, "Give a reason for the amendment.")
    locked = await lock_item(session, actor.clinic_id, item_id)
    if not locked.ok:
        return failure(locked.code or BookingErrorCode.NOT_FOUND, locked.message)
    order, item = locked.unwrap().order, locked.unwrap().item
    if item.status not in allowed_sources(LabAction.AMEND, settings.requires_verification):
        return _wrong_state(LabAction.AMEND, item.status)
    computed = await _compute(session, order, item, values, settings)
    if not computed.ok:
        return failure(computed.code or BookingErrorCode.VALIDATION, computed.message)
    rows = [(p, c) for p, c in computed.unwrap() if c is not None]
    if not rows:
        return failure(BookingErrorCode.VALIDATION, "Enter the corrected values.")

    current = {
        r.parameter_id: r
        for r in (
            await session.scalars(
                select(LabResult).where(LabResult.order_item_id == item.id, LabResult.is_current)
            )
        ).all()
    }
    latest_rows = await session.execute(
        select(LabResult.parameter_id, func.max(LabResult.version))
        .where(LabResult.order_item_id == item.id)
        .group_by(LabResult.parameter_id)
    )
    latest = {pid: version for pid, version in latest_rows}
    for parameter, _c in rows:
        old = current.get(parameter.id)
        if old is not None:
            old.is_current = False
    await session.flush()
    for parameter, c in rows:
        result = LabResult(
            order_item_id=item.id,
            parameter_id=parameter.id,
            version=latest.get(parameter.id, 0) + 1,
            amended_reason=reason.strip(),
            entered_by=actor.user_id,
            entered_at=utcnow(),
        )
        snapshot_result(result, c)
        session.add(result)
    await session.flush()
    add_event(session, order, "amended", actor.user_id, item=item)
    order.reviewed_at = None
    order.reviewed_by = None
    await _alert_criticals(session, order, item)
    await ensure_generated_report(session, order, actor.user_id, settings)
    await enqueue(session, order.clinic_id, order.patient_id, RecordSourceType.LAB_RESULT, order.id)
    await refresh_order(session, order)
    return success(order)
