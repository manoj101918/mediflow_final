"""Split rendered text into embedding-sized chunks (RecursiveCharacterTextSplitter)."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.db.models import ReportType
from app.services.ingestion.render import RenderedSource, human_date

REPORT_TYPE_TEXT = {
    ReportType.LAB: "lab report",
    ReportType.IMAGING: "imaging report",
    ReportType.DISCHARGE_SUMMARY: "discharge summary",
    ReportType.REFERRAL: "referral letter",
    ReportType.OLD_PRESCRIPTION: "old prescription",
    ReportType.OTHER: "document",
}


@dataclass(frozen=True)
class Chunk:
    content: str
    metadata: dict[str, Any]


def splitter(chunk_size: int, overlap: int) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=min(overlap, chunk_size // 2),
        separators=["\n\n", "\n", ". ", "; ", ", ", " ", ""],
    )


def chunk_source(source: RenderedSource, chunk_size: int, overlap: int) -> list[Chunk]:
    """Normally one chunk per piece; long pieces are split, each part keeping the heading."""
    split = splitter(chunk_size, overlap)
    chunks: list[Chunk] = []
    for piece in source.pieces:
        if len(piece.content) <= chunk_size:
            chunks.append(Chunk(piece.content, dict(piece.metadata)))
            continue
        for i, part in enumerate(split.split_text(piece.content)):
            text = part if i == 0 else f"{source.heading}\n{part}"
            chunks.append(Chunk(text, {**piece.metadata, "part": i + 1}))
    return chunks


def report_heading(title: str, report_type: ReportType, report_date: date | None) -> str:
    kind = REPORT_TYPE_TEXT[report_type]
    when = f", dated {human_date(report_date)}" if report_date else ""
    return f"Report: {title} ({kind}{when})"


def chunk_report_pages(
    pages: list[str],
    *,
    title: str,
    report_type: ReportType,
    report_date: date | None,
    chunk_size: int,
    overlap: int,
) -> list[Chunk]:
    """Each chunk is prefixed with the report's title, type, date and page number."""
    heading = report_heading(title, report_type, report_date)
    split = splitter(chunk_size, overlap)
    chunks: list[Chunk] = []
    for number, text in enumerate(pages, start=1):
        if not text.strip():
            continue
        for part in split.split_text(text):
            chunks.append(
                Chunk(
                    f"{heading}, page {number}:\n{part}",
                    {
                        "report_title": title,
                        "report_type": report_type.value,
                        "report_date": report_date.isoformat() if report_date else None,
                        "page": number,
                        "label": f"{title}, p. {number}",
                    },
                )
            )
    return chunks
