"""Map the answer's [n] markers to the numbered sources given to the model."""

import re
from typing import Any

from app.services.rag.prompt import Source

# [2], [2, 4], [2][4], [2,4]; some models add a locator suffix: [2†L3-L5]
_MARKER = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)(?:†[^\]]*)?\]")
# Some models (gpt-oss) cite with full-width brackets: 【2】 / 【2†source】
_FULL_WIDTH = str.maketrans({"【": "[", "】": "]"})


def normalize_markers(text: str) -> str:
    """Full-width citation brackets -> ASCII, so every UI and parser sees [n]."""
    return text.translate(_FULL_WIDTH)


def clean_markers(text: str) -> str:
    """[n†locator] -> [n] (for the stored answer)."""
    return _MARKER.sub(lambda m: f"[{m.group(1)}]", normalize_markers(text))


def cited_numbers(answer: str) -> list[int]:
    answer = normalize_markers(answer)
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
