"""Inbound bookings from bots (API key) and the front desk's view of them."""

import hmac
import json
from datetime import timedelta
from typing import Annotated, Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Header, Query, Request, Response, status
from pydantic import ValidationError

from app.api.results import not_found
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.rate_limit import inbound_rate_limit, limiter
from app.db.models import InboundBookingRequest, InboundStatus
from app.deps import DbSession, FrontDeskUser
from app.schemas.doctors import SlotOut
from app.schemas.inbound import (
    InboundAppointmentOut,
    InboundBookingIn,
    InboundBookingOut,
    InboundEnvelope,
    InboundRequestOut,
)
from app.services import inbound as service
from app.services.booking.timeutil import utcnow

router = APIRouter(tags=["inbound"])
logger = structlog.get_logger(__name__)

MAX_BODY_BYTES = 16_384


def _check_api_key(provided: str | None) -> None:
    expected = get_settings().inbound_api_key.get_secret_value().encode()
    if provided is None or not hmac.compare_digest(provided.encode(), expected):
        raise AppError(401, "INVALID_API_KEY", "Missing or invalid API key.")


def _validation_details(exc: ValidationError) -> list[dict[str, Any]]:
    return [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]


def _out(outcome: service.InboundOutcome) -> InboundBookingOut:
    appointment = outcome.appointment
    return InboundBookingOut(
        request_id=outcome.request.id,
        status=outcome.request.status,
        duplicate=outcome.duplicate,
        appointment=(
            InboundAppointmentOut(
                id=appointment.id,
                token_number=appointment.token_number,
                status=appointment.status,
                starts_at=appointment.starts_at,
                doctor_id=appointment.doctor_id,
                doctor_name=outcome.doctor_name or "",
            )
            if appointment is not None
            else None
        ),
        error_code=outcome.code.value if outcome.code else None,
        message=outcome.message,
        suggested_slots=[
            SlotOut(starts_at=s.starts_at, ends_at=s.ends_at) for s in outcome.suggested
        ],
    )


@router.post(
    "/bookings/inbound",
    responses={
        200: {"description": "Duplicate: this external_ref was already received"},
        202: {"description": "Stored for the front desk (needs_review), with suggested slots"},
        401: {"description": "Missing or invalid X-API-Key"},
        422: {"description": "Malformed or rejected request"},
        429: {"description": "Rate limit exceeded"},
    },
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(inbound_rate_limit)
async def inbound_booking(
    request: Request,
    response: Response,
    session: DbSession,
    x_api_key: Annotated[str | None, Header()] = None,
) -> InboundBookingOut:
    """Book from a WhatsApp / voice bot (header `X-API-Key`).

    Body: `channel`, `external_ref` (unique per request; retries are safe), `caller_phone`,
    `patient_name`, and optionally `doctor_id`, `requested_time` (ISO with offset), `reason`.
    201 = booked as pending_confirmation; 202 = kept for the front desk (see
    `suggested_slots`); 200 = duplicate of an earlier request.
    """
    _check_api_key(x_api_key)
    settings = get_settings()
    if settings.inbound_clinic_id is None:
        raise AppError(503, "NOT_CONFIGURED", "Inbound bookings are not configured.")
    clinic_id = settings.inbound_clinic_id

    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise AppError(413, "PAYLOAD_TOO_LARGE", "Request body is too large.")
    try:
        raw = json.loads(body)
    except ValueError as exc:
        raise AppError(422, "VALIDATION", "Body must be JSON.") from exc
    if not isinstance(raw, dict):
        raise AppError(422, "VALIDATION", "Body must be a JSON object.")
    try:
        envelope = InboundEnvelope.model_validate(raw)
    except ValidationError as exc:
        raise AppError(
            422, "VALIDATION", "channel and external_ref are required.", _validation_details(exc)
        ) from exc

    stored, duplicate = await service.record_request(
        session, clinic_id, envelope.channel, envelope.external_ref.strip(), raw
    )
    log = logger.bind(inbound_request_id=str(stored.id), channel=envelope.channel.value)
    if duplicate:
        log.info("inbound_duplicate", status=stored.status.value)
        response.status_code = status.HTTP_200_OK
        return _out(await service.describe(session, stored))

    try:
        data = InboundBookingIn.model_validate(raw)
    except ValidationError as exc:
        await service.mark_rejected(session, clinic_id, stored.id, "VALIDATION: invalid fields")
        log.info("inbound_rejected", reason="validation")
        raise AppError(
            422,
            "VALIDATION",
            "The request is missing or has invalid fields.",
            {"request_id": str(stored.id), "errors": _validation_details(exc)},
        ) from exc

    outcome = await service.process_request(
        session,
        clinic_id,
        stored.id,
        service.InboundBooking(
            channel=data.channel,
            external_ref=data.external_ref.strip(),
            caller_phone=data.caller_phone,
            patient_name=data.patient_name,
            doctor_id=data.doctor_id,
            requested_time=data.requested_time,
            reason=data.reason,
        ),
    )
    log.info("inbound_processed", status=outcome.request.status.value, code=outcome.code)
    if outcome.request.status is InboundStatus.REJECTED:
        raise AppError(
            422,
            outcome.code.value if outcome.code else "VALIDATION",
            outcome.message,
            {"request_id": str(stored.id)},
        )
    if outcome.request.status is InboundStatus.NEEDS_REVIEW:
        response.status_code = status.HTTP_202_ACCEPTED
    return _out(outcome)


# --- Front desk ------------------------------------------------------------------------------


def _request_out(request: InboundBookingRequest, doctor_name: str | None) -> InboundRequestOut:
    return InboundRequestOut(
        id=request.id,
        channel=request.channel,
        external_ref=request.external_ref,
        caller_phone=request.caller_phone,
        parsed_patient_name=request.parsed_patient_name,
        requested_doctor_id=request.requested_doctor_id,
        requested_doctor_name=doctor_name,
        requested_time=request.requested_time,
        status=request.status,
        error=request.error,
        appointment_id=request.appointment_id,
        created_at=request.created_at,
    )


@router.get("/inbound-requests")
async def list_inbound_requests(
    session: DbSession,
    user: FrontDeskUser,
    status_filter: Annotated[
        InboundStatus | None, Query(alias="status")
    ] = InboundStatus.NEEDS_REVIEW,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
) -> list[InboundRequestOut]:
    """Recent bot requests (default: the ones the front desk still has to handle)."""
    rows = await service.list_requests(
        session, user.clinic_id, status_filter, utcnow() - timedelta(days=days)
    )
    return [_request_out(request, name) for request, name in rows]


@router.post("/inbound-requests/{request_id}/dismiss")
async def dismiss_inbound_request(
    request_id: UUID, session: DbSession, user: FrontDeskUser
) -> InboundRequestOut:
    """Mark a request handled (e.g. after calling the patient back or booking manually)."""
    request = await service.mark_rejected(
        session, user.clinic_id, request_id, f"Handled by {user.full_name}"
    )
    if request is None:
        raise not_found("Request")
    return _request_out(request, None)
