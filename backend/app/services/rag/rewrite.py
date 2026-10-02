"""Turn a follow-up ("and before that?") into a standalone search query using recent turns.

Skipped on the first turn (saves a model call on the free tier). Any failure falls back to the
original question: retrieval should degrade, not the whole answer.
"""

import re

import structlog
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

logger = structlog.get_logger(__name__)

REWRITE_SYSTEM = (
    "You rewrite a doctor's follow-up question about one patient into a standalone search "
    "query for that patient's records. Keep medicine names, test names, dates and numbers. "
    "Return only the query, without quotes or explanation."
)

# Signals that are about time, so recent visits are included directly (see chat.py).
_RECENCY = re.compile(
    r"\b(last|latest|recent|recently|previous|prior|since|trend|trends|over time|history|"
    r"so far|progress|changed?|compare|comparison|timeline|all visits)\b",
    re.I,
)
_LAST_N = re.compile(r"\blast\s+(\d{1,2}|two|three|four|five|six)\b", re.I)
_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def recency_window(question: str) -> int | None:
    """How many recent visits to include directly, or None if the question isn't about time.

    "last 3 visits" -> 3; "trend" / "history" / "over time" -> all (large number);
    "latest", "since last visit" -> 2 (the last visit and the one before).
    """
    if not _RECENCY.search(question):
        return None
    match = _LAST_N.search(question)
    if match:
        raw = match.group(1).lower()
        return int(raw) if raw.isdigit() else _WORDS[raw]
    if re.search(
        r"\b(trend|trends|over time|history|so far|progress|timeline|all visits)\b", question, re.I
    ):
        return 50
    return 2


async def rewrite_question(
    model: BaseChatModel, history: list[tuple[str, str]], question: str
) -> str:
    if not history:
        return question
    turns = "\n".join(
        f"{'Doctor' if role == 'user' else 'Assistant'}: {text[:600]}" for role, text in history
    )
    prompt = (
        f"Rewrite the latest question as a standalone search query.\n\n"
        f"Conversation so far:\n{turns}\n\nDoctor's question: {question}"
    )
    try:
        result = await model.ainvoke([SystemMessage(REWRITE_SYSTEM), HumanMessage(prompt)])
    except Exception as exc:
        logger.info("query_rewrite_failed", error_type=type(exc).__name__)
        return question
    rewritten = result.text.strip().strip('"').strip()
    return rewritten[:500] if rewritten else question
