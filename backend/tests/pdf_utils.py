"""Small generated files for upload / extraction tests."""

from fpdf import FPDF

# Smallest valid PNG header + IHDR is enough for type sniffing.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def make_pdf(pages: list[str]) -> bytes:
    """A text PDF with one page per string (pypdf can extract it)."""
    pdf = FPDF()
    pdf.set_font("Helvetica", size=11)
    for page in pages:
        pdf.add_page()
        pdf.multi_cell(0, 6, page)
    return bytes(pdf.output())


def make_blank_pdf(pages: int = 1) -> bytes:
    """A PDF with pages but no text layer (like a scan without OCR)."""
    pdf = FPDF()
    for _ in range(pages):
        pdf.add_page()
        pdf.rect(20, 20, 100, 60)
    return bytes(pdf.output())
