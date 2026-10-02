"""Citation markers in model answers (no database)."""

from datetime import date
from uuid import uuid4

from app.services.rag.citations import citations_for, cited_numbers, clean_markers
from app.services.rag.prompt import Source


def test_ascii_full_width_and_locator_markers() -> None:
    answer = "Allergic to penicillin【1】. HbA1c 6.9 % [3†L2-L4]; dose 1000 mg [2, 3][4]."
    assert cited_numbers(answer) == [1, 3, 2, 4]
    assert clean_markers(answer) == (
        "Allergic to penicillin[1]. HbA1c 6.9 % [3]; dose 1000 mg [2, 3][4]."
    )


def test_unknown_numbers_are_dropped() -> None:
    sources = [Source(1, "summary", uuid4(), "Patient summary", date(2026, 10, 2), "x")]
    assert [c["n"] for c in citations_for("Fact [1] and [9].", sources)] == [1]
