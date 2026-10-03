"""Channel-agnostic booking conversation (WhatsApp, the voice simulator, later the phone line).

Channel adapters normalize messages into `InboundMsg`, call `run_turn`, and deliver the queued
replies. Nothing here imports FastAPI.
"""

from app.services.conversation.turn import (
    ConversationBusyError,
    TurnResult,
    is_opted_out,
    load_conversation,
    run_turn,
    set_preference,
)
from app.services.conversation.types import InboundMsg, Option, Reply

__all__ = [
    "ConversationBusyError",
    "InboundMsg",
    "Option",
    "Reply",
    "TurnResult",
    "is_opted_out",
    "load_conversation",
    "run_turn",
    "set_preference",
]
