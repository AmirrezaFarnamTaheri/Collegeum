"""Constrained child process: extract bounded, nonencrypted PDF text; no network."""
from __future__ import annotations

import io
import json
import re
import sys
from urllib.parse import urlsplit

MAX_PDF_BYTES = 1024 * 1024
MAX_PDF_PAGES = 8
MAX_PDF_TEXT = 24000


def _safe_web_link(value: object) -> bool:
    """Check PDF URI actions without opening, normalizing or following links."""
    if not isinstance(value, str) or not value:
        return False
    # urlsplit discards some embedded controls before parsing: reject them
    # and ambiguous backslashes explicitly before interpreting authority.
    if any(ch.isspace() or ord(ch) < 32 or ch == "\\" for ch in value):
        return False
    try:
        target = urlsplit(value)
        return bool(
            target.scheme in {"http", "https"}
            and target.hostname
            and target.username is None
            and target.password is None
            and target.port in {None, 80, 443}
            and "%" not in target.netloc
        )
    except ValueError:
        return False


def inspect(data: bytes) -> dict[str, str]:
    if len(data) > MAX_PDF_BYTES:
        return {"status": "document_unverified", "reason": "oversize"}
    if not data.startswith(b"%PDF-"):
        return {"status": "document_unverified", "reason": "not_pdf"}
    try:
        from pypdf import PdfReader
        from pypdf.generic import ArrayObject, DictionaryObject

        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            return {"status": "document_unverified", "reason": "encrypted"}
        if (len(reader.pages) == 0 or len(reader.pages) > MAX_PDF_PAGES):
            return {"status": "document_unverified", "reason": "page_count"}
        catalog = reader.trailer["/Root"]
        if any(name in catalog for name in (
            "/OpenAction", "/AA", "/Names", "/AcroForm", "/Collection",
        )):
            # This reviewer does not inspect or execute embedded actions,
            # attachments, interactive forms or document scripting.
            return {"status": "document_unverified", "reason": "active_pdf"}
        parts = []
        for page in reader.pages:
            # PDF actions may be attached to the PAGE or ANNOTATIONS without
            # appearing in /Root. Inspect these before trusting extracted text.
            if "/AA" in page or "/PresSteps" in page:
                return {"status": "document_unverified", "reason": "active_pdf"}
            annotations = page.get("/Annots", ArrayObject())
            if hasattr(annotations, "get_object"):
                annotations = annotations.get_object()
            if not isinstance(annotations, ArrayObject) or len(annotations) > 100:
                return {"status": "document_unverified", "reason": "active_pdf"}
            for reference in annotations:
                annotation = reference.get_object() if hasattr(
                    reference, "get_object"
                ) else reference
                if not isinstance(annotation, DictionaryObject):
                    return {"status": "document_unverified", "reason": "active_pdf"}
                if any(key in annotation for key in (
                    "/AA", "/JS", "/FS", "/RichMediaContent", "/RichMediaSettings",
                )) or annotation.get("/Subtype") in {
                    "/Widget", "/FileAttachment", "/RichMedia",
                    "/Screen", "/Movie", "/Sound",
                }:
                    return {"status": "document_unverified", "reason": "active_pdf"}
                if "/A" in annotation:
                    action = annotation["/A"]
                    if hasattr(action, "get_object"):
                        action = action.get_object()
                    if not isinstance(action, DictionaryObject):
                        return {"status": "document_unverified", "reason": "active_pdf"}
                    # Only non-executing navigation is permitted. In particular,
                    # /Next chains and launch/remote/script actions are rejected.
                    kind = action.get("/S")
                    allowed = (
                        {"/S", "/URI", "/Type"} if kind == "/URI"
                        else {"/S", "/D", "/Type"} if kind == "/GoTo"
                        else set()
                    )
                    if (not allowed or not set(action).issubset(allowed)
                            or (kind == "/URI" and not _safe_web_link(action.get("/URI")))
                            or (kind == "/GoTo" and "/D" not in action)):
                        return {"status": "document_unverified", "reason": "active_pdf"}
            txt = page.extract_text() or ""
            if not txt.strip():
                return {"status": "document_unverified", "reason": "unreadable_page"}
            parts.append(txt)
            if sum(len(part) for part in parts) > MAX_PDF_TEXT:
                return {"status": "document_unverified", "reason": "text_oversize"}
        text = re.sub(r"\s+", " ", " ".join(parts)).strip()
        if len(text) < 100:
            return {"status": "document_unverified", "reason": "no_usable_text"}
        return {"status": "ok", "text": text}
    except Exception:
        return {"status": "document_unverified", "reason": "invalid_pdf"}


def main() -> int:
    # No system/network operations or PDF writes occur in this worker.
    data = sys.stdin.buffer.read(MAX_PDF_BYTES + 1)
    sys.stdout.write(json.dumps(inspect(data), ensure_ascii=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
