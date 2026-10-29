"""PDF text extraction helper for job postings with direct PDF flyers."""
from __future__ import annotations

import io
import logging
import re

log = logging.getLogger(__name__)

__all__ = ["is_pdf", "extract_pdf_text", "clean_pdf_text"]

_PDF_MAGIC = b"%PDF-"


def _looks_like_markup(content: bytes | str) -> bool:
    """Recognize HTML/XML gateway pages regardless of filename and MIME hints.

    Nonempty response-body evidence is stronger than a .pdf suffix or an
    application/pdf response header; preserve metadata-only behavior for
    empty content.
    """
    if isinstance(content, bytes):
        prefix = content[:512].lstrip()
        prefix = prefix.removeprefix(bytes.fromhex("efbbbf")).lstrip()
        return prefix.startswith(b"<")
    prefix = content[:512].lstrip()
    prefix = prefix.removeprefix(chr(0xfeff)).lstrip()
    return prefix.startswith("<")


def is_pdf(content: bytes | str, content_type: str = "", url: str = "") -> bool:
    """Check if binary payload, content-type header, or URL corresponds to a PDF."""
    if isinstance(content, bytes) and content.startswith(_PDF_MAGIC):
        return True
    if isinstance(content, str) and content.startswith("%PDF-"):
        return True
    if content and _looks_like_markup(content):
        return False
    if "application/pdf" in (content_type or "").lower():
        return True
    clean_url = (url or "").split("?")[0].lower()
    return clean_url.endswith(".pdf")


def extract_pdf_text(content: bytes, max_chars: int = 20000) -> str:
    """Extract plain text from binary PDF data using pypdf.

    Returns an empty string if parsing fails or produces no usable text.
    """
    if not content or _looks_like_markup(content):
        return ""
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(content))
        pages_text: list[str] = []
        total_len = 0

        for page in reader.pages:
            try:
                txt = page.extract_text() or ""
            except Exception as page_err:
                log.debug("Failed extracting text from PDF page: %s", page_err)
                txt = ""
            cleaned = clean_pdf_text(txt)
            if cleaned:
                pages_text.append(cleaned)
                total_len += len(cleaned)
            if total_len >= max_chars:
                break

        full_text = "\n\n".join(pages_text).strip()
        return full_text[:max_chars]
    except Exception as exc:
        log.warning("PDF extraction failed: %s", exc)
        return ""


def clean_pdf_text(text: str) -> str:
    """Clean common artifacts from extracted PDF text."""
    if not text:
        return ""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    compacted = [line for line in lines if line]
    return "\n".join(compacted)
