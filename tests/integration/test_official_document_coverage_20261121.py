"""Issue #183: contextual IEB index recall and reviewed-document audit safety."""
from __future__ import annotations

import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from predoc_pipeline.core.official_call_rules import call_key, receipt_key
from predoc_pipeline.publish.official_calls import eligible_calls, official_calls_health
from tools.official_call_pdf_review import fetch_reviewed_pdf
from tools.official_document_review_journal import load_review_records, record_review
from tools.official_document_safety import NoDocumentRedirect
from tools.update_official_calls import discover_links, refresh_sources

NOW = datetime(2026, 11, 21, 12, tzinfo=UTC)
INDEX = "https://ieb.ub.edu/en/call-for-application/"
PDF = "https://ieb.ub.edu/wp-content/uploads/2026/11/IEB-PhD-Scholarship-2027-28.pdf"
HTML = "https://ieb.ub.edu/en/phd-scholarship-in-economics-2027/"
ENERGY = ("https://ieb.ub.edu/en/call-for-expressions-of-interest-"
          "phd-fellowship-in-energy-and-climate-economics/")
SOURCE = {
    "id": "ieb-index", "institution": "Barcelona Institute of Economics (IEB)",
    "country_code": "ES", "mode": "index", "url": INDEX,
    "approved_documents": [{
        "url": PDF, "title": "PhD Scholarship in Economics",
        "institution_marker": "Barcelona Institute of Economics",
        "canonical_html_url": HTML,
    }],
}
REGISTRY = {"kind": "official_phd_call_sources", "version": 1, "sources": [SOURCE]}
OLD = {"kind": "official_phd_call_observations", "version": 1,
       "sources": [], "calls": []}


def indexed_html() -> str:
    return f"""
      <h3>PhD Scholarship in Economics 2027</h3>
      <a href="{HTML}">Web personal</a>
      <h3>Call for expressions of interest: PhD Fellowship in Energy and Climate Economics</h3>
      <a href="{ENERGY}">Web personal</a>
      <h3>Postdoctoral position in Environmental and Energy Economics</h3>
      <a href="/postdoctoral-position/">Web personal</a>
      <h3>PhD Fellowship in Gender Economics (closed)</h3>
      <a href="https://untrusted.example/phd-fellowship">Web personal</a>
      <h3>Unrelated informational notice</h3>
      <a href="/contact/">Web personal</a>
      <h3>PhD Scholarship in Economics 2027</h3>
      <a href="{PDF}">Descargar PDF</a>
    """


def _result(*, digest: str = "a" * 64, status: str = "document_review_only"):
    return {
        "status": status, "source_id": SOURCE["id"], "official_url": PDF,
        "reviewed_at": "2026-11-21T11:00:00Z",
        "document_sha256": digest,
        "canonical_html_url": HTML,
        "automatic_publication": False,
    }


def test_ieb_generic_web_personal_links_resolve_contextually_not_from_metadata():
    assert discover_links(indexed_html(), SOURCE) == [HTML, ENERGY]


def test_contextual_index_discovery_only_creates_candidates_and_coverage_counts():
    responses = {
        INDEX: {"status": "ok", "html": indexed_html()},
        HTML: {"status": "ok", "html": "<h1>Unverified scholarship</h1>"},
        ENERGY: {"status": "ok", "html": "<h1>Unverified fellowship</h1>"},
    }
    catalog = refresh_sources(REGISTRY, OLD, now=NOW,
                              fetcher=lambda url: responses[url])
    summary = catalog["sources"][0]
    assert summary["discovered_links"] == 2
    assert summary["index_empty"] is False
    assert summary["rechecked_links"] == 0
    assert summary["unsupported_documents"] == 1
    assert summary["document_links_by_format"] == {"pdf": 1, "doc": 0, "docx": 0}
    assert summary["document_candidates"] == [PDF]
    assert not eligible_calls(catalog, now=NOW)


def test_public_health_sums_html_rechecks_robots_and_document_format_counts(tmp_path: Path):
    catalog_path = tmp_path / "official_phd_calls.json"
    catalog = {
        "kind": "official_phd_call_observations", "version": 1,
        "calls": [], "sources": [{
            "status": "robots_disallowed", "index_empty": False,
            "discovered_links": 2, "rechecked_links": 1,
            "unsupported_documents": 3, "failed_details": 1,
            "blocked_details": 1,
            "document_links_by_format": {"pdf": 2, "doc": 1, "docx": 0},
        }],
    }
    catalog_path.write_text(json.dumps(catalog))
    health = official_calls_health(catalog_path, tmp_path / "receipts.json", now=NOW)
    assert health["discovered_html_links"] == 2
    assert health["historical_rechecks"] == 1
    assert health["document_links_by_format"] == {"pdf": 2, "doc": 1, "docx": 0}
    assert health["robots_blocked_sources"] == 1
    assert health["robots_blocked_details"] == 1


def test_recorded_review_requires_approved_source_and_is_review_only(tmp_path: Path):
    journal = tmp_path / "official_document_reviews.json"
    assert record_review(journal, _result(), registry=REGISTRY,
                         method="live_fetch") is True
    assert record_review(journal, _result(), registry=REGISTRY,
                         method="live_fetch") is False
    rows = load_review_records(journal, registry=REGISTRY)
    assert len(rows) == 1
    assert rows[0]["status"] == "document_review_only"
    assert rows[0]["document_sha256"] == "a" * 64
    assert "evidence_excerpt" not in rows[0]
    assert rows[0]["method"] == "live_fetch"
    assert record_review(journal, _result(digest="b" * 64),
                         registry=REGISTRY, method="live_fetch") is True
    rows = load_review_records(journal, registry=REGISTRY)
    assert len(rows) == 2
    assert rows[0]["document_sha256"] != rows[1]["document_sha256"]


def test_corrupt_or_unapproved_journal_never_gets_overwritten(tmp_path: Path):
    journal = tmp_path / "official_document_reviews.json"
    journal.write_text('{"unexpected":"schema"}')
    with pytest.raises(ValueError):
        record_review(journal, _result(), registry=REGISTRY, method="live_fetch")
    assert journal.read_text() == '{"unexpected":"schema"}'
    journal.unlink()
    for changes in (
        {"status": "verified"}, {"official_url": PDF + "?changed=1"},
        {"source_id": "different-index"}, {"document_sha256": "not-a-digest"},
        {"automatic_publication": True},
    ):
        with pytest.raises(ValueError):
            record_review(journal, {**_result(), **changes},
                          registry=REGISTRY, method="live_fetch")
        assert not journal.exists()


def test_failed_review_reason_is_recorded_separately_from_unsupported_links(tmp_path: Path):
    journal = tmp_path / "official_document_reviews.json"
    failed = {
        "status": "robots_disallowed", "source_id": SOURCE["id"],
        "official_url": PDF, "reviewed_at": "2026-11-21T11:10:00Z",
        "reason": "robots_disallowed",
    }
    assert record_review(journal, failed, registry=REGISTRY,
                         method="live_fetch")
    catalog_path = tmp_path / "official_phd_calls.json"
    catalog_path.write_text(json.dumps({
        "kind": "official_phd_call_observations", "version": 1,
        "sources": [{"status": "ok", "unsupported_documents": 12}], "calls": [],
    }))
    health = official_calls_health(catalog_path, tmp_path / "receipts.json", now=NOW)
    assert health["unsupported_documents"] == 12
    assert health["document_review_failures"] == 1
    assert health["document_review_robots_blocks"] == 1
    assert health["document_review_successes"] == 0
    assert health["document_review_status"] == "recorded"


def test_redirect_handler_never_follows_same_host_alternative_document():
    handler = NoDocumentRedirect()
    request = urllib.request.Request(PDF)
    with pytest.raises(ValueError, match="unsafe_redirect"):
        handler.redirect_request(request, None, 302, "Found", {},
                                 "https://ieb.ub.edu/other.pdf")


def test_pdf_fetch_refuses_redirect_even_if_target_same_host_and_robots_allow():
    robot = Mock()
    robot.can_fetch.return_value = True
    response = Mock()
    response.read.return_value = b"User-agent: *\nAllow: /"
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    redirects: list[NoDocumentRedirect] = []

    def make_opener(handler):
        redirects.append(handler)
        opener = Mock()

        def open_request(request, timeout=8):
            if request.full_url.endswith("/robots.txt"):
                return response
            return handler.redirect_request(
                request, None, 302, "Found", {},
                "https://ieb.ub.edu/other.pdf")

        opener.open.side_effect = open_request
        return opener

    with (patch("urllib.robotparser.RobotFileParser", return_value=robot),
          patch("urllib.request.build_opener", side_effect=make_opener)):
        result = fetch_reviewed_pdf(PDF, SOURCE)
    assert result["status"] == "unsafe_redirect"
    assert len(redirects) == 1
    assert isinstance(redirects[0], NoDocumentRedirect)


def test_same_host_html_language_alias_cannot_rebroadcast_recorded_official_call():
    from urllib.parse import urlsplit

    canonical = {
        "official_url": HTML,
        "institution": SOURCE["institution"],
        "title": "PhD Scholarship in Economics 2027",
        "deadline_iso": "2026-12-11", "intake_year": 2027,
        "kind": "phd_scholarship",
    }
    delivered = {call_key(canonical): {
        **canonical, "state": "confirmed", "message_id": 133,
    }}
    alias = {
        **canonical, "official_url": "https://ieb.ub.edu/phd-scholarship-in-economics-2027/",
    }
    assert urlsplit(alias["official_url"]).path != urlsplit(HTML).path
    assert call_key(alias) != call_key(canonical)
    assert receipt_key(alias, delivered) == call_key(canonical)

    # Same cutoff does not imply identical scholarships or identical cycles.
    distinct = {**alias, "title": "PhD Fellowship in Energy and Climate Economics"}
    assert receipt_key(distinct, delivered) is None
    new_cycle = {**alias, "deadline_iso": "2027-12-11", "intake_year": 2028}
    assert receipt_key(new_cycle, delivered) is None
    other_host = {
        **alias, "official_url": "https://other-institute.example/phd-scholarship-2027",
    }
    assert receipt_key(other_host, delivered) is None
