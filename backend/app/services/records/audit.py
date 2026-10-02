"""Patient-record access log: who opened which chart, viewed which report, asked the chatbot.

Only ids and the action are stored, never the question text (that lives in the chat tables).
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PatientRecordAccessLog, RecordAccessAction
from app.services.booking.actor import StaffActor


def log_access(
    session: AsyncSession,
    actor: StaffActor,
    patient_id: UUID,
    action: RecordAccessAction,
    *,
    appointment_id: UUID | None = None,
    session_id: UUID | None = None,
    report_id: UUID | None = None,
) -> None:
    """Add a log row to the session; the caller's transaction commits it."""
    session.add(
        PatientRecordAccessLog(
            clinic_id=actor.clinic_id,
            patient_id=patient_id,
            user_id=actor.user_id,
            action=action,
            appointment_id=appointment_id,
            session_id=session_id,
            report_id=report_id,
        )
    )


async def record_access(
    session: AsyncSession,
    actor: StaffActor,
    patient_id: UUID,
    action: RecordAccessAction,
    *,
    appointment_id: UUID | None = None,
    report_id: UUID | None = None,
) -> None:
    """Log a read-only access in its own commit."""
    log_access(
        session, actor, patient_id, action, appointment_id=appointment_id, report_id=report_id
    )
    await session.commit()
