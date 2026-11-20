"""Constrained child process: extract bounded, nonencrypted PDF text; no network."""
from __future__ import annotations

import io
import json
import re
import sys

MAX_PDF_BYTES = 1024 * 1024
MAX_PDF_PAGES = 8
MAX_PDF_TEXT = 24000


def inspect(data: bytes) -> dict[str, str]:
    if len(data) > MAX_PDF_BYTES:
        return {"status": "document_unverified", "reason": "oversize"}
    if not data.startswith(b"%PDF-"):
        return {"status": "document_unverified", "reason": "not_pdf"}
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            return {"status": "document_unverified", "reason": "encrypted"}
        if (len(reader.pages) == 0 or len(reader.pages) > MAX_PDF_PAGES):
            return {"status": "document_unverified", "reason": "page_count"}
        catalog = reader.trailer["/Root"]
        if any(name in catalog for name in ("/OpenAction", "/AA", "/Names")):
            # This reviewer does not inspect or execute embedded actions,
            # attachments, or document scripting.
            return {"status": "document_unverified", "reason": "active_pdf"}
        parts = []
        for page in reader.pages:
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
