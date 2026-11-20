"""Official PDF calls are reviewed only from explicit approved institutional URLs."""
from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from predoc_pipeline.publish.official_calls import eligible_calls
from tools.official_call_pdf_review import MAX_PDF_BYTES, review_pdf_bytes, safe_pdf_url
from tools.update_official_calls import discover_document_links, unsupported_document_count

NOW = datetime(2026, 11, 20, 8, tzinfo=UTC)
INDEX = "https://ieb.ub.edu/convocatorias/"
PDF = "https://ieb.ub.edu/wp-content/uploads/2026/11/IEB-PhD-Scholarship-2027-28.pdf"
SOURCE = {
    "id": "ieb-calls-pdf-review", "mode": "index", "url": INDEX,
    "institution": "Barcelona Institute of Economics (IEB)", "country_code": "ES",
    "approved_documents": [{
        "url": PDF, "title": "PhD Scholarship in Economics",
        "institution_marker": "Barcelona Institute of Economics",
        "canonical_html_url": "https://ieb.ub.edu/en/phd-scholarship-in-economics-2027/",
    }],
}


def _pdf(lines, *, pages=1, encrypted=False):
    """Create a real PDF with an embedded text stream; no screenshots or OCR."""
    writer = PdfWriter()
    for idx in range(pages):
        page = writer.add_blank_page(width=612, height=792)
        if idx:
            continue
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        font_ref = writer._add_object(font)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref}),
        })
        stream = DecodedStreamObject()
        commands = " BT /F1 12 Tf 30 700 Td 14 TL " + " ".join(
            f"({line}) Tj T*" for line in lines
        ) + " ET "
        stream.set_data(commands.encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("secret")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _evidence_text():
    return [
        "Barcelona Institute of Economics IEB - University of Barcelona",
        "Call for applications: PhD Scholarship in Economics",
        "Full-time scholarship to pursue a PhD in Economics.",
        "Starting in September or October 2027.",
        "Candidates must have completed a Master degree by summer 2027.",
        "Interested candidates must complete both steps by 11 December 2026.",
    ]


def test_pdf_links_discovered_from_nearby_scholarship_heading_not_download_label():
    html = """
      <h3>PhD Scholarship in Economics 2027</h3>
      <a href="/wp-content/uploads/2026/11/IEB-PhD-Scholarship-2027-28.pdf">
        Descargar PDF
      </a>
      <h3>Postdoctoral Fellowship in Energy Economics</h3>
      <a href="/wp-content/uploads/2026/11/postdoc.pdf">Download PDF</a>
      <h3>PhD Scholarship in Statistics 2027</h3>
      <a href="https://offsite.org/award.pdf">Download PDF</a>
      <a href="/wp-content/uploads/2026/11/IEB-PhD-Scholarship-2027-28.pdf">
        Duplicate PDF
      </a>
    """
    assert discover_document_links(html, SOURCE) == [PDF]
    assert unsupported_document_count(html, SOURCE) == 1


def test_document_url_is_https_exact_institution_host_no_redirect_query_or_credentials():
    assert safe_pdf_url(PDF, INDEX) == PDF
    for candidate in [
        "http://ieb.ub.edu/prize.pdf", "https://evil.example/phd.pdf",
        "https://ieb.ub.edu.evil.example/doc.pdf",
        "https://x:password@ieb.ub.edu/doc.pdf",
        "https://ieb.ub.edu/doc.pdf?dl=1", "https://ieb.ub.edu/doc.pdf#page=1",
        "https://ieb.ub.edu/doc.docx", "https://ieb.ub.edu/news",
        "https://ieb.ub.edu:8443/doc.pdf",
    ]:
        assert safe_pdf_url(candidate, INDEX) is None, candidate


def test_no_pdf_without_explicit_source_approval_is_eligible_or_parsed():
    source = {**SOURCE, "approved_documents": []}
    row = review_pdf_bytes(
        _pdf(_evidence_text()), url=PDF, source=source, now=NOW,
        content_type="application/pdf",
    )
    assert row["status"] == "document_unverified"
    assert row["reason"] == "not_approved"


def test_valid_official_pdf_has_independent_text_evidence_but_never_auto_publishes():
    row = review_pdf_bytes(
        _pdf(_evidence_text()), url=PDF, source=SOURCE, now=NOW,
        content_type="application/pdf",
    )
    # PDF is reviewed in isolation; the canonical HTML call has already been
    # delivered. The pdf URL itself must not become an extra Telegram key.
    assert row["status"] == "document_review_only"
    assert row["intake_year"] == 2027
    assert row["deadline_iso"] == "2026-12-11"
    assert row["canonical_html_url"] == SOURCE["approved_documents"][0]["canonical_html_url"]
    assert row["document_sha256"]
    assert "complete both steps by" in row["evidence_excerpt"]
    assert eligible_calls({
        "kind": "official_phd_call_observations", "version": 1, "calls": [row],
    }, now=NOW) == []


def test_document_review_rejects_html_disguised_as_pdf_and_wrong_mime():
    pdf = _pdf(_evidence_text())
    for content, mime in [
        (b"<html>Access denied</html>", "application/pdf"),
        (pdf, "text/html"),
        (b"%PDF-spoofed-binary", "application/pdf"),
        (b"", "application/pdf"),
    ]:
        row = review_pdf_bytes(
            content, url=PDF, source=SOURCE, now=NOW, content_type=mime,
        )
        assert row["status"] == "document_unverified"


def test_document_review_rejects_scans_encrypted_and_too_many_pages():
    for payload in [
        _pdf([""], pages=1),
        _pdf(_evidence_text(), encrypted=True),
        _pdf(_evidence_text(), pages=9),
    ]:
        row = review_pdf_bytes(
            payload, url=PDF, source=SOURCE, now=NOW,
            content_type="application/pdf",
        )
        assert row["status"] == "document_unverified"


def test_document_review_rejects_outdated_ambiguous_or_fabricated_official_evidence():
    for lines in [
        _evidence_text()[:4],
        [line.replace("11 December 2026", "11 December 2025")
         for line in _evidence_text()],
        [line.replace("11 December 2026", "11 December 2026 or 20 January 2027")
         for line in _evidence_text()],
        [line.replace("Barcelona Institute of Economics", "University of Elsewhere")
         for line in _evidence_text()],
        [line.replace("PhD Scholarship in Economics", "Workshop in Statistics")
         for line in _evidence_text()],
    ]:
        row = review_pdf_bytes(
            _pdf(lines), url=PDF, source=SOURCE, now=NOW,
            content_type="application/pdf",
        )
        assert row["status"] == "document_unverified", row


def test_document_review_enforces_strict_byte_limit():
    row = review_pdf_bytes(
        b"%PDF-1.7\n" + b"0" * MAX_PDF_BYTES,
        url=PDF, source=SOURCE, now=NOW, content_type="application/pdf",
    )
    assert row["status"] == "document_unverified"
    assert row["reason"] == "oversize"


def test_document_review_is_not_a_production_catalogue_or_telegram_trigger(tmp_path: Path):
    report = tmp_path / "pdf-review.json"
    row = review_pdf_bytes(
        _pdf(_evidence_text()), url=PDF, source=SOURCE, now=NOW,
        content_type="application/pdf",
    )
    report.write_text(json.dumps(row))
    assert row["status"] != "verified"
    assert row["official_url"] == PDF
    assert row["evidence_url"] == PDF
    assert Path(report).read_text().startswith("{")
