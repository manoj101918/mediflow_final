"""Map the answer's [n] markers to the numbered sources given to the model."""

import re
from typing import Any

from app.services.rag.prompt import Source

# [2], [2, 4], [2][4], [2,4]
_MARKER = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")


def cited_numbers(answer: str) -> list[int]:
    """Source numbers in order of first appearance."""
    seen: list[int] = []
    for group in _MARKER.findall(answer):
        for raw in group.split(","):
            n = int(raw.strip())
            if n not in seen:
                seen.append(n)
    return seen


def citations_for(answer: str, sources: list[Source]) -> list[dict[str, Any]]:
    """Structured citations for markers that point at real sources (unknown numbers dropped)."""
    by_number = {s.n: s for s in sources}
    return [by_number[n].citation() for n in cited_numbers(answer) if n in by_number]
