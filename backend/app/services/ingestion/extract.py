"""Report text extraction with pypdf (text-layer PDFs only; no OCR / vision model).

Images and scanned PDFs have no text layer: they stay viewable but are not searchable
(`no_text`). Damaged or password-protected PDFs raise ExtractionError (`failed`, retryable).
"""

import io
import logging
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PyPdfError

# pypdf logs warnings about malformed (but readable) PDFs; they are not actionable here.
logging.getLogger("pypdf").setLevel(logging.ERROR)


class ExtractionError(Exception):
    """The file could not be read. The message is safe to show to staff."""


@dataclass(frozen=True)
class ExtractedPdf:
    # Text of each page, in order (page 1 = index 0); may be empty for image-only pages.
    pages: list[str]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def total_chars(self) -> int:
        return sum(len(p.strip()) for p in self.pages)


def _clean(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_pdf(data: bytes) -> ExtractedPdf:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractionError("The PDF is password-protected.")
        pages = [_clean(page.extract_text() or "") for page in reader.pages]
    except ExtractionError:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, OSError) as exc:
        raise ExtractionError("The PDF could not be read (damaged or unsupported).") from exc
    return ExtractedPdf(pages)


def looks_scanned(pdf: ExtractedPdf, min_chars_per_page: int) -> bool:
    """Too little text for its page count: probably a scan without a text layer."""
    return pdf.page_count == 0 or pdf.total_chars < min_chars_per_page * pdf.page_count
