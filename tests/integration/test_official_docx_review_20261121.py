"""Bounded, explicitly approved DOCX review must never trigger publication."""
from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from unittest.mock import Mock, patch
from xml.sax.saxutils import escape

import pytest

from predoc_pipeline.publish.official_calls import eligible_calls
from tools.official_call_docx_review import (
    DOCX_MIME,
    approved_docx,
    fetch_reviewed_docx,
    review_docx_bytes,
    safe_docx_url,
)
from tools.official_docx_worker import MAX_DOCX_BYTES, inspect
from tools.update_official_calls import validate_sources

INDEX = "https://ieb.ub.edu/convocatorias/"
DOCX = "https://ieb.ub.edu/wp-content/uploads/2026/11/phd-scholarship-2027.docx"
SOURCE = {
    "id": "ieb-docx-review", "mode": "index", "url": INDEX,
    "institution": "Barcelona Institute of Economics (IEB)", "country_code": "ES",
    "approved_documents": [{
        "url": DOCX, "title": "PhD Scholarship in Economics",
        "institution_marker": "Barcelona Institute of Economics",
        "canonical_html_url": "https://ieb.ub.edu/en/phd-scholarship-in-economics-2027/",
    }],
}
NOW = datetime(2026, 11, 20, 8, tzinfo=UTC)
TYPES = b'''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''
RELS = b'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''


def document(lines: list[str], *, extra: dict[str, bytes] | None = None) -> bytes:
    body = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    body += "".join(f"<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>" for line in lines)
    body += "</w:body></w:document>"
    parts = {"[Content_Types].xml": TYPES, "_rels/.rels": RELS,
             "word/document.xml": body.encode(), **(extra or {})}
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    return target.getvalue()


def evidence() -> list[str]:
    return [
        "Barcelona Institute of Economics IEB University of Barcelona",
        "PhD Scholarship in Economics: full time funded PhD scholarship",
        "Starting in September 2027. Candidates must hold a master degree.",
        "Interested candidates must complete both steps by 11 December 2026.",
        "C/ John M. Keynes, 1-11, 08034 Barcelona. Tel. +34 93 403 40 00.",
    ]


def test_official_docx_review_only_from_document_body_not_filename():
    row = review_docx_bytes(document(evidence()), url=DOCX, source=SOURCE,
                            now=NOW, content_type=DOCX_MIME)
    assert row["status"] == "document_review_only", row
    assert row["deadline_iso"] == "2026-12-11"
    assert row["intake_year"] == 2027
    assert row["automatic_publication"] is False
    assert row["canonical_html_url"] == SOURCE["approved_documents"][0]["canonical_html_url"]
    assert eligible_calls({"kind": "official_phd_call_observations", "version": 1,
                           "calls": [row]}, now=NOW) == []


def test_unapproved_document_or_changed_url_is_held():
    missing = {**SOURCE, "approved_documents": []}
    assert approved_docx(missing, DOCX) is None
    assert review_docx_bytes(document(evidence()), url=DOCX, source=missing,
                             now=NOW, content_type=DOCX_MIME)["reason"] == "not_approved"
    for candidate in (DOCX + "?new=1", "http://ieb.ub.edu/a.docx",
                      "https://other.example/a.docx", "https://ieb.ub.edu/a.doc",
                      "https://ieb.ub.edu:8443/a.docx"):
        assert safe_docx_url(candidate, INDEX) is None


def test_review_registry_accepts_explicit_docx_but_rejects_bad_host_and_duplicate():
    config = {"kind": "official_phd_call_sources", "version": 1, "sources": [SOURCE]}
    validate_sources(config)
    for bad in (DOCX + "?token=x", "https://other.example/a.docx",
                "https://ieb.ub.edu/a.doc"):
        changed = {**SOURCE, "approved_documents": [
            {**SOURCE["approved_documents"][0], "url": bad}]}
        with pytest.raises(ValueError):
            validate_sources({**config, "sources": [changed]})
    with pytest.raises(ValueError):
        validate_sources({**config, "sources": [{
            **SOURCE, "approved_documents": SOURCE["approved_documents"] * 2}]})


def test_docx_requires_independent_eligibility_geography_and_current_deadline():
    modified = [
        [part.replace("Candidates must", "Participants may").replace("candidates must", "participants may") for part in evidence()],
        [part.replace("08034 Barcelona", "Madrid").replace("+34", "+44")
         for part in evidence()],
        [part.replace("11 December 2026", "11 December 2025") for part in evidence()],
        [part.replace("11 December 2026", "11 December 2026 or 20 January 2027")
         for part in evidence()],
        [part.replace("Barcelona Institute of Economics", "Another Institute")
         for part in evidence()],
    ]
    for lines in modified:
        row = review_docx_bytes(document(lines), url=DOCX, source=SOURCE,
                                now=NOW, content_type=DOCX_MIME)
        assert row["status"] == "document_unverified", row


def test_docx_rejects_macro_external_relations_and_malformed_zip():
    active = [
        {"word/vbaProject.bin": b"macro"},
        {"word/embeddings/object.bin": b"ole"},
        {"word/_rels/document.xml.rels": b'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r9" Type="x" TargetMode="External" Target="https://evil.example"/></Relationships>'''},
        {"../escape.txt": b"traversal"},
        {"word/huge.xml": b"x" * (4 * 1024 * 1024)},
        {"word/document.xml": b'<!DOCTYPE root [<!ENTITY exp SYSTEM "file:///etc/passwd">]><root/>'},
    ]
    for extra in active:
        assert inspect(document(evidence(), extra=extra))["status"] == "document_unverified"
    for blob in (b"", b"<html>error</html>", b"%PDF-1.4", b"PK\x03\x04BAD",
                 b"x" * (MAX_DOCX_BYTES + 1), document([])):
        assert inspect(blob)["status"] == "document_unverified"


def test_wrong_mime_and_oversize_are_held_without_parsing():
    for blob, kind in ((document(evidence()), "text/html"),
                       (b"<html>403</html>", DOCX_MIME),
                       (b"x" * (MAX_DOCX_BYTES + 1), DOCX_MIME)):
        row = review_docx_bytes(blob, url=DOCX, source=SOURCE,
                                now=NOW, content_type=kind)
        assert row["status"] == "document_unverified"


def test_robots_denial_never_fetches_approved_document():
    opener = Mock()
    reply = Mock()
    reply.read.return_value = b"User-agent: *\nDisallow: /"
    reply.__enter__ = Mock(return_value=reply)
    reply.__exit__ = Mock(return_value=None)
    opener.open.return_value = reply
    robots = Mock()
    robots.can_fetch.return_value = False
    with (patch("urllib.request.build_opener", return_value=opener),
          patch("urllib.robotparser.RobotFileParser", return_value=robots)):
        result = fetch_reviewed_docx(DOCX, SOURCE)
    assert result["status"] == "robots_disallowed"
    assert opener.open.call_count == 1


def test_worker_rejects_unreviewed_format_and_bounded_limits():
    assert inspect(document(["p"] * 151))["status"] == "document_unverified"
    assert inspect(document(["x" * 25000]))["status"] == "document_unverified"
    for name in ("ins", "del", "fldSimple", "instrText", "altChunk"):
        custom = ("<w:document xmlns:w=\"http://schemas.openxmlformats.org/"
                  "wordprocessingml/2006/main\"><w:body><w:p>"
                  + "<w:r><w:t>" + "x" * 130 + "</w:t></w:r>"
                  + f"<w:{name}>changed</w:{name}>"
                  + "</w:p></w:body></w:document>").encode()
        assert inspect(document(evidence(), extra={"word/document.xml": custom}))[
            "status"] == "document_unverified"
