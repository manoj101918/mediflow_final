"""Tell the patient what reception decided about a bot booking.

Approve -> confirmation with doctor, day, time and token number. Reject -> apology with up
to three alternative slots; the conversation continues from there (the patient picks one and
confirms as usual). Both are essential free-form messages, so they need the 24-hour window;
when it's closed (and paid templates are off) nothing is sent and reception is told to call.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Appointment,
    AppointmentSource,
    BotChannel,
    BotConversation,
    Doctor,
    MessageOutbox,
    OutboxStatus,
    Patient,
)
from app.services.booking.timeutil import local_date, utcnow
from app.services.bot_jobs import queue
from app.services.conversation import data
from app.services.conversation.engine import SLOT
from app.services.conversation.i18n import day_label, t, time_label
from app.services.conversation.options import options_to_draft
from app.services.conversation.types import Language, Option, Reply
from app.services.messaging.dispatch import DispatchDeps, blocked_reason

Decision = Literal["approval", "rejection"]
NotificationStatus = Literal[
    "queued",
    "window_closed",
    "opted_out",
    "no_consent",
    "limit",
    "not_configured",
    "no_conversation",
]
ALTERNATIVES = 3
_CHANNELS = {
    AppointmentSource.WHATSAPP: BotChannel.WHATSAPP,
    AppointmentSource.VOICE: BotChannel.WEB_VOICE,
}


@dataclass(frozen=True)
class Notification:
    status: NotificationStatus
    channel: BotChannel
    phone_e164: str
    outbox_id: UUID | None = None


async def _alternatives(
    session: AsyncSession, clinic_id: UUID, doctor_id: UUID, now: datetime, tz: ZoneInfo
) -> list[datetime]:
    today = local_date(now, tz)
    found: list[datetime] = []
    for offset in range(data.BOOKING_DAYS):
        found += await data.free_slots(
            session, clinic_id, doctor_id, today + timedelta(offset), now
        )
        if len(found) >= ALTERNATIVES:
            break
    return found[:ALTERNATIVES]


async def notify_decision(
    session: AsyncSession,
    clinic_id: UUID,
    appointment_id: UUID,
    decision: Decision,
    deps: DispatchDeps,
    *,
    now: datetime | None = None,
) -> Notification | None:
    """Queue the message for a bot booking (None for bookings made by staff). Commits."""
    moment = now or utcnow()
    row = (
        await session.execute(
            select(
                Appointment.source,
                Appointment.starts_at,
                Appointment.token_number,
                Appointment.doctor_id,
                Appointment.patient_id,
                Patient.full_name,
                Patient.phone,
                Doctor.full_name.label("doctor_name"),
            )
            .join(Patient, Patient.id == Appointment.patient_id)
            .join(Doctor, Doctor.id == Appointment.doctor_id)
            .where(Appointment.id == appointment_id, Appointment.clinic_id == clinic_id)
        )
    ).first()
    if row is None or row.source not in _CHANNELS:
        return None
    channel = _CHANNELS[row.source]
    conversation = await session.scalar(
        select(BotConversation).where(
            BotConversation.clinic_id == clinic_id,
            BotConversation.channel == channel,
            BotConversation.phone_e164 == row.phone,
        )
    )
    if conversation is None:
        return Notification("no_conversation", channel, row.phone)
    conversation_id, version = conversation.id, conversation.version
    lang: Language = conversation.language if conversation.language in ("te", "hi", "en") else "en"  # type: ignore[assignment]

    clinic = await data.clinic_info(session, clinic_id)
    today = local_date(moment, clinic.tz)
    day = day_label(lang, local_date(row.starts_at, clinic.tz), today)
    when = time_label(row.starts_at, clinic.tz)
    if decision == "approval":
        reply = Reply(
            text=t(
                lang,
                "approved",
                patient=row.full_name,
                doctor=row.doctor_name,
                day=day,
                time=when,
                token=row.token_number,
            ),
            essential=True,
        )
    else:
        slots = await _alternatives(session, clinic_id, row.doctor_id, moment, clinic.tz)
        options = [
            Option(
                f"t:{s.isoformat()}",
                time_label(s, clinic.tz),
                day_label(lang, local_date(s, clinic.tz), today),
            )
            for s in slots
        ]
        if options:
            reply = Reply(
                text=t(lang, "rejected", day=day, time=when),
                rows=tuple(options),
                list_label=t(lang, "list_choose"),
                essential=True,
            )
            # The patient continues from the slot list: pick, give a reason, confirm.
            await session.execute(
                update(BotConversation)
                .where(BotConversation.id == conversation_id)
                .values(
                    state=SLOT,
                    selected_patient_id=row.patient_id,
                    failed_parse_count=0,
                    version=version + 1,
                    draft={
                        "mode": "book",
                        "patient_name": row.full_name,
                        "doctor_id": str(row.doctor_id),
                        "doctor_name": row.doctor_name,
                        "options": options_to_draft(options),
                        "all_options": options_to_draft(options),
                        "offset": 0,
                        "prompt": reply.text,
                        "buttons": False,
                    },
                )
            )
        else:
            reply = Reply(text=t(lang, "rejected_no_slots", day=day, time=when), essential=True)

    outbox_id = await session.scalar(
        insert(MessageOutbox)
        .values(
            clinic_id=clinic_id,
            conversation_id=conversation_id,
            appointment_id=appointment_id,
            channel=channel,
            phone_e164=row.phone,
            kind=decision,
            essential=True,
            idempotency_key=f"{decision}:{appointment_id}",
            body=reply.as_body(),
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(MessageOutbox.id)
    )
    if outbox_id is None:  # already notified (e.g. a retried request)
        await session.rollback()
        existing = await session.scalar(
            select(MessageOutbox).where(
                MessageOutbox.idempotency_key == f"{decision}:{appointment_id}"
            )
        )
        status: NotificationStatus = "queued"
        if (
            existing is not None
            and existing.status is OutboxStatus.BLOCKED
            and existing.blocked_reason
        ):
            status = existing.blocked_reason  # type: ignore[assignment]
        return Notification(status, channel, row.phone, existing.id if existing else None)

    outbox = await session.get(MessageOutbox, outbox_id)
    assert outbox is not None  # noqa: S101 - inserted above
    reason = (
        await blocked_reason(session, outbox, deps, moment)
        if channel is BotChannel.WHATSAPP
        else None
    )
    if reason is not None:
        outbox.status, outbox.blocked_reason = OutboxStatus.BLOCKED, reason
        await session.commit()
        return Notification(reason, channel, row.phone, outbox_id)  # type: ignore[arg-type]
    await queue.enqueue(session, clinic_id, "outbox", ref_id=outbox_id)
    await session.commit()
    return Notification("queued", channel, row.phone, outbox_id)
