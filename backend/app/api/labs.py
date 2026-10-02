"""In-house lab: doctor ordering and results, the lab worklist and workflow, alerts, status."""

from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Response, UploadFile, status

from app.api.lab_catalog import lab_test_out
from app.api.reports import Storage, read_limited, report_out
from app.api.results import HTTP_STATUS, unwrap
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import LabOrder, LabResult, LabSample, ReportType
from app.deps import AuthUser, DbSession, LabUser, clinic_today, staff_actor
from app.schemas.labs import (
    ClinicSettingsOut,
    LabAcknowledge,
    LabAlertOut,
    LabAmendIn,
    LabCancel,
    LabCollect,
    LabComment,
    LabInboxRowOut,
    LabItemDetailOut,
    LabItemOut,
    LabOrderCreate,
    LabOrderDetailOut,
    LabOrderOut,
    LabOrderStatusOut,
    LabParameterEntryOut,
    LabPatientOut,
    LabPreviousOut,
    LabRangeOut,
    LabReason,
    LabRepeatOut,
    LabResultOut,
    LabResultsIn,
    LabReviewedOut,
    LabSampleOut,
    LabStatusCountsOut,
    LabTestOut,
    LabTestStatusOut,
    LabTrendOut,
    LabTrendPointOut,
    LabWorklistRowOut,
)
from app.schemas.reports import ReportOut
from app.services.booking.actor import StaffActor
from app.services.booking.results import BookingErrorCode, BookingResult
from app.services.labs import alerts, orders, read, workflow
from app.services.labs.catalog import load_catalog, requires_verification
from app.services.labs.ranges import age_on, format_number, range_label
from app.services.records.access import is_clinician
from app.services.records.reports import NewReport, upload_report

router = APIRouter(tags=["labs"])


def _f(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _forbidden() -> AppError:
    return AppError(403, BookingErrorCode.FORBIDDEN.value, "You do not have access to this action.")


# ---------------------------------------------------------------------------
# Conversions
# ---------------------------------------------------------------------------


def result_out(r: LabResult) -> LabResultOut:
    return LabResultOut(
        id=r.id,
        parameter_id=r.parameter_id,
        parameter_code=r.parameter_code,
        parameter_name=r.parameter_name,
        unit=r.unit,
        value_type=r.value_type,
        value_numeric=_f(r.value_numeric),
        value_text=r.value_text,
        range_label=r.range_label,
        ref_low=_f(r.ref_low),
        ref_high=_f(r.ref_high),
        flag=r.flag,
        version=r.version,
        is_current=r.is_current,
        amended_reason=r.amended_reason,
        entered_at=r.entered_at,
    )


def sample_out(s: LabSample) -> LabSampleOut:
    return LabSampleOut(
        id=s.id,
        sample_code=s.sample_code,
        sample_type=s.sample_type,
        container=s.container,
        collected_at=s.collected_at,
        rejected_at=s.rejected_at,
        rejected_reason=s.rejected_reason,
    )


def _item_fields(view: read.ItemView) -> dict[str, object]:
    i = view.item
    return {
        "id": i.id,
        "test_id": i.test_id,
        "test_code": i.test_code,
        "test_name": i.test_name,
        "status": i.status,
        "sample_id": i.sample_id,
        "sample_code": view.sample.sample_code if view.sample else None,
        "rejection_reason": i.rejection_reason,
        "return_comment": i.return_comment,
        "entered_at": i.entered_at,
        "verified_at": i.verified_at,
        "released_at": i.released_at,
        "cancelled_reason": i.cancelled_reason,
        "results": [result_out(r) for r in view.results],
        "history": [result_out(r) for r in view.history],
    }


def order_out(view: read.OrderView) -> LabOrderOut:
    o = view.order
    return LabOrderOut(
        id=o.id,
        order_number=o.order_number,
        patient_id=o.patient_id,
        patient_name=view.patient.full_name,
        appointment_id=o.appointment_id,
        consultation_id=o.consultation_id,
        ordering_doctor_id=o.ordering_doctor_id,
        ordering_doctor_name=view.doctor_name,
        priority=o.priority,
        status=o.status,
        clinical_note=o.clinical_note,
        cancelled_reason=o.cancelled_reason,
        reviewed_at=o.reviewed_at,
        report_id=view.report_id,
        created_at=o.created_at,
        updated_at=o.updated_at,
        items=[LabItemOut.model_validate(_item_fields(i)) for i in view.items],
        samples=[sample_out(s) for s in view.samples],
    )


def detail_out(detail: read.LabOrderDetail) -> LabOrderDetailOut:
    view = detail.order
    patient = view.patient
    items = []
    for d in detail.items:
        parameters = []
        for pv in d.parameters:
            r, prev = pv.reference, pv.previous
            parameters.append(
                LabParameterEntryOut(
                    id=pv.parameter.id,
                    code=pv.parameter.code,
                    name=pv.parameter.name,
                    unit=pv.parameter.unit,
                    value_type=pv.parameter.value_type,
                    choices=list(pv.parameter.choices),
                    decimals=pv.parameter.decimals,
                    delta_percent=_f(pv.parameter.delta_percent),
                    range=LabRangeOut(
                        low=_f(r.low),
                        high=_f(r.high),
                        critical_low=_f(r.critical_low),
                        critical_high=_f(r.critical_high),
                        text_normal=r.text_normal,
                        label=range_label(r),
                    )
                    if r
                    else None,
                    previous=LabPreviousOut(
                        value_numeric=_f(prev.value_numeric),
                        value_text=prev.value_text,
                        unit=prev.unit,
                        flag=prev.flag,
                        released_at=prev.released_at,
                        order_number=prev.order_number,
                    )
                    if prev
                    else None,
                    delta_warning=pv.delta_warning,
                )
            )
        items.append(
            LabItemDetailOut.model_validate(
                {
                    **_item_fields(d.view),
                    "category": d.test.category,
                    "sample_type": d.test.sample_type,
                    "container": d.test.container,
                    "parameters": parameters,
                }
            )
        )
    return LabOrderDetailOut(
        order=order_out(view),
        patient=LabPatientOut(
            id=patient.id,
            full_name=patient.full_name,
            phone=patient.phone,
            gender=patient.gender,
            age=detail.age,
        ),
        requires_verification=detail.requires_verification,
        items=items,
    )


# ---------------------------------------------------------------------------
# Catalog (doctors and lab)
# ---------------------------------------------------------------------------


def _doctor_or_lab(actor: StaffActor) -> None:
    if not (is_clinician(actor) or actor.is_lab):
        raise _forbidden()


@router.get("/lab/catalog")
async def lab_catalog(session: DbSession, user: AuthUser) -> list[LabTestOut]:
    _doctor_or_lab(staff_actor(user))
    return [lab_test_out(t) for t in await load_catalog(session, user.clinic_id, active_only=True)]


# ---------------------------------------------------------------------------
# Doctors: ordering, results, trends, inbox, alerts
# ---------------------------------------------------------------------------


async def _order_or_404(session: DbSession, clinic_id: UUID, order_id: UUID) -> LabOrderOut:
    view = await read.order_view(session, clinic_id, order_id, released_values_only=True)
    if view is None:
        raise AppError(404, BookingErrorCode.NOT_FOUND.value, "Lab order not found.")
    return order_out(view)


@router.post("/appointments/{appointment_id}/lab-orders", status_code=status.HTTP_201_CREATED)
async def create_lab_order(
    appointment_id: UUID, body: LabOrderCreate, session: DbSession, user: AuthUser
) -> LabOrderOut:
    order = unwrap(
        await orders.create_order(
            session,
            staff_actor(user),
            appointment_id,
            orders.NewLabOrder(body.test_ids, body.priority, body.clinical_note),
        )
    )
    return await _order_or_404(session, user.clinic_id, order.id)


@router.get("/appointments/{appointment_id}/lab-orders")
async def appointment_lab_orders(
    appointment_id: UUID, session: DbSession, user: AuthUser
) -> list[LabOrderOut]:
    views = unwrap(await read.appointment_orders(session, staff_actor(user), appointment_id))
    return [order_out(v) for v in views]


@router.get("/patients/{patient_id}/lab-orders/last")
async def last_lab_order(patient_id: UUID, session: DbSession, user: AuthUser) -> LabRepeatOut:
    return LabRepeatOut(
        test_ids=unwrap(await orders.last_order_test_ids(session, staff_actor(user), patient_id))
    )


@router.post("/lab/orders/{order_id}/cancel")
async def cancel_lab_order(
    order_id: UUID, body: LabCancel, session: DbSession, user: AuthUser
) -> LabOrderOut:
    actor = staff_actor(user)
    unwrap(await orders.cancel_items(session, actor, order_id, body.item_ids, body.reason))
    return await _order_or_404(session, user.clinic_id, order_id)


@router.get("/patients/{patient_id}/lab-results")
async def patient_lab_results(
    patient_id: UUID, session: DbSession, user: AuthUser
) -> list[LabOrderOut]:
    views = unwrap(await read.patient_lab_results(session, staff_actor(user), patient_id))
    return [order_out(v) for v in views]


@router.get("/patients/{patient_id}/lab-trends")
async def patient_lab_trends(
    patient_id: UUID, session: DbSession, user: AuthUser
) -> list[LabTrendOut]:
    series = unwrap(await read.lab_trends(session, staff_actor(user), patient_id))
    return [
        LabTrendOut(
            code=s.code,
            name=s.name,
            unit=s.unit,
            points=[
                LabTrendPointOut(
                    value=float(p.value),
                    flag=p.flag,
                    ref_low=_f(p.ref_low),
                    ref_high=_f(p.ref_high),
                    released_at=p.released_at,
                    order_id=p.order_id,
                    order_item_id=p.order_item_id,
                    order_number=p.order_number,
                )
                for p in s.points
            ],
        )
        for s in series
    ]


@router.get("/lab/inbox")
async def lab_inbox(session: DbSession, user: AuthUser) -> list[LabInboxRowOut]:
    rows = unwrap(await read.results_inbox(session, staff_actor(user)))
    return [
        LabInboxRowOut(order=order_out(r.view), abnormal=r.abnormal, critical=r.critical)
        for r in rows
    ]


@router.post("/lab/orders/{order_id}/review")
async def review_lab_order(order_id: UUID, session: DbSession, user: AuthUser) -> LabReviewedOut:
    done = unwrap(await alerts.mark_reviewed(session, staff_actor(user), order_id))
    return LabReviewedOut(order_id=done.order_id, reviewed_at=done.reviewed_at)


def _value_text(r: LabResult) -> str:
    if r.value_numeric is not None:
        return format_number(r.value_numeric)
    return r.value_text or ""


@router.get("/lab/alerts")
async def lab_alerts(session: DbSession, user: AuthUser) -> list[LabAlertOut]:
    views = unwrap(await alerts.open_alerts(session, staff_actor(user)))
    return [
        LabAlertOut(
            id=v.alert.id,
            patient_id=v.alert.patient_id,
            patient_name=v.patient_name,
            order_id=v.alert.order_id,
            order_number=v.order_number,
            parameter_name=v.result.parameter_name,
            value=_value_text(v.result),
            unit=v.result.unit,
            flag=v.result.flag,
            range_label=v.result.range_label,
            created_at=v.alert.created_at,
        )
        for v in views
    ]


@router.post("/lab/alerts/{alert_id}/acknowledge", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge_alert(
    alert_id: UUID, body: LabAcknowledge, session: DbSession, user: AuthUser
) -> Response:
    unwrap(await alerts.acknowledge(session, staff_actor(user), alert_id, body.note))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Status only (front desk and doctors): never values
# ---------------------------------------------------------------------------


def _front_desk_or_doctor(actor: StaffActor) -> None:
    if not (actor.is_front_desk or is_clinician(actor)):
        raise _forbidden()


@router.get("/lab/status-summary")
async def lab_status_summary(
    session: DbSession, user: AuthUser, day: date | None = None
) -> list[LabStatusCountsOut]:
    actor = staff_actor(user)
    _front_desk_or_doctor(actor)
    counts = await read.status_summary(session, actor, day or clinic_today(user))
    return [
        LabStatusCountsOut(appointment_id=a, pending=c.pending, ready=c.ready)
        for a, c in counts.items()
    ]


@router.get("/patients/{patient_id}/lab-orders")
async def patient_lab_orders(
    patient_id: UUID, session: DbSession, user: AuthUser
) -> list[LabOrderStatusOut]:
    actor = staff_actor(user)
    _front_desk_or_doctor(actor)
    views = unwrap(await read.patient_order_statuses(session, actor, patient_id))
    return [
        LabOrderStatusOut(
            id=v.order.id,
            order_number=v.order.order_number,
            appointment_id=v.order.appointment_id,
            ordering_doctor_name=v.doctor_name,
            priority=v.order.priority,
            status=v.order.status,
            created_at=v.order.created_at,
            tests=[
                LabTestStatusOut(test_name=i.item.test_name, status=i.item.status) for i in v.items
            ],
        )
        for v in views
    ]


# ---------------------------------------------------------------------------
# Lab staff: worklist and workflow
# ---------------------------------------------------------------------------


@router.get("/lab/settings")
async def lab_settings(session: DbSession, user: LabUser) -> ClinicSettingsOut:
    return ClinicSettingsOut(
        lab_requires_verification=await requires_verification(session, user.clinic_id)
    )


@router.get("/lab/worklist")
async def lab_worklist(
    session: DbSession,
    user: LabUser,
    tab: read.WorklistTab = read.WorklistTab.TO_COLLECT,
    q: str | None = None,
) -> list[LabWorklistRowOut]:
    rows = unwrap(await read.worklist(session, staff_actor(user), tab, q))
    today = clinic_today(user)
    return [
        LabWorklistRowOut(
            order_id=r.order.id,
            order_number=r.order.order_number,
            priority=r.order.priority,
            status=r.order.status,
            created_at=r.order.created_at,
            patient_id=r.patient.id,
            patient_name=r.patient.full_name,
            patient_phone=r.patient.phone,
            patient_gender=r.patient.gender,
            patient_age=age_on(today, r.patient.date_of_birth, r.patient.age_years),
            ordering_doctor_name=r.doctor_name,
            counts=r.counts,
            tests=r.tests,
            sample_codes=r.sample_codes,
        )
        for r in rows
    ]


async def _detail(session: DbSession, actor: StaffActor, order_id: UUID) -> LabOrderDetailOut:
    return detail_out(unwrap(await read.lab_order_detail(session, actor, order_id)))


@router.get("/lab/orders/{order_id}")
async def lab_order(order_id: UUID, session: DbSession, user: LabUser) -> LabOrderDetailOut:
    return await _detail(session, staff_actor(user), order_id)


async def _then_detail(
    session: DbSession, actor: StaffActor, result: BookingResult[LabOrder]
) -> LabOrderDetailOut:
    order = unwrap(result)
    return await _detail(session, actor, order.id)


@router.post("/lab/orders/{order_id}/collect")
async def collect_samples(
    order_id: UUID, body: LabCollect, session: DbSession, user: LabUser
) -> LabOrderDetailOut:
    actor = staff_actor(user)
    return await _then_detail(
        session, actor, await workflow.collect(session, actor, order_id, body.item_ids)
    )


@router.post("/lab/samples/{sample_id}/reject")
async def reject_sample(
    sample_id: UUID, body: LabReason, session: DbSession, user: LabUser
) -> LabOrderDetailOut:
    actor = staff_actor(user)
    return await _then_detail(
        session, actor, await workflow.reject_sample(session, actor, sample_id, body.reason)
    )


def _values(body: LabResultsIn | LabAmendIn) -> list[workflow.ResultValue]:
    return [workflow.ResultValue(v.parameter_id, v.value) for v in body.values]


@router.put("/lab/items/{item_id}/results")
async def save_results(
    item_id: UUID, body: LabResultsIn, session: DbSession, user: LabUser
) -> LabOrderDetailOut:
    actor = staff_actor(user)
    result = await workflow.save_results(
        session, actor, item_id, _values(body), confirm_critical=body.confirm_critical
    )
    return await _then_detail(session, actor, result)


@router.post("/lab/items/{item_id}/submit")
async def submit_results(item_id: UUID, session: DbSession, user: LabUser) -> LabOrderDetailOut:
    actor = staff_actor(user)
    return await _then_detail(session, actor, await workflow.submit(session, actor, item_id))


@router.post("/lab/items/{item_id}/verify")
async def verify_results(item_id: UUID, session: DbSession, user: LabUser) -> LabOrderDetailOut:
    actor = staff_actor(user)
    return await _then_detail(session, actor, await workflow.verify(session, actor, item_id))


@router.post("/lab/items/{item_id}/release")
async def release_results(item_id: UUID, session: DbSession, user: LabUser) -> LabOrderDetailOut:
    actor = staff_actor(user)
    return await _then_detail(session, actor, await workflow.release(session, actor, item_id))


@router.post("/lab/items/{item_id}/send-back")
async def send_back_results(
    item_id: UUID, body: LabComment, session: DbSession, user: LabUser
) -> LabOrderDetailOut:
    actor = staff_actor(user)
    return await _then_detail(
        session, actor, await workflow.send_back(session, actor, item_id, body.comment)
    )


@router.post("/lab/items/{item_id}/amend")
async def amend_results(
    item_id: UUID, body: LabAmendIn, session: DbSession, user: LabUser
) -> LabOrderDetailOut:
    actor = staff_actor(user)
    return await _then_detail(
        session, actor, await workflow.amend(session, actor, item_id, _values(body), body.reason)
    )


@router.post("/lab/orders/{order_id}/attachment", status_code=status.HTTP_201_CREATED)
async def attach_lab_pdf(
    order_id: UUID,
    session: DbSession,
    user: LabUser,
    storage: Storage,
    file: Annotated[UploadFile, File()],
) -> ReportOut:
    """The lab machine's own PDF for an order: stored with the order, never embedded."""
    order = await read.order_view(session, user.clinic_id, order_id, released_values_only=True)
    if order is None:
        raise AppError(404, BookingErrorCode.NOT_FOUND.value, "Lab order not found.")
    max_bytes = get_settings().report_max_mb * 1024 * 1024
    data = await read_limited(file, max_bytes)
    if data is None:
        raise AppError(
            HTTP_STATUS[BookingErrorCode.FILE_TOO_LARGE],
            BookingErrorCode.FILE_TOO_LARGE.value,
            f"The file is larger than {get_settings().report_max_mb} MB.",
        )
    report = unwrap(
        await upload_report(
            session,
            storage,
            staff_actor(user),
            order.order.patient_id,
            NewReport(
                title=f"Lab machine report {order.order.order_number}",
                report_type=ReportType.LAB,
                report_date=clinic_today(user),
                data=data,
                consultation_id=order.order.consultation_id,
                lab_order_id=order_id,
            ),
            max_bytes=max_bytes,
        )
    )
    return report_out(report)
