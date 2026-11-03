"""Inspect official EURAXESS public search form without recording HTML or tokens."""
from __future__ import annotations

import json

from tools.probe_life_sciences_sources import search_page_evidence


def test_search_form_field_names_and_method_are_visible_without_raw_values():
    html = """
    <html><body><form action="/jobs/search" method="get">
      <input name="search_api_fulltext" type="search"
             placeholder="Field, subject, position, location, keyword" value="genomics">
      <input type="hidden" name="form_build_id" value="sensitive-form-value">
      <input type="hidden" name="csrf_token" value="private-secret">
      <input name="email" type="text" value="someone@example.org">
      <button>Search</button>
    </form><h2>Search results (24)</h2></body></html>
    """
    report = search_page_evidence(
        html, "https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=keywords%3Agenomics"
    )
    assert report["search_input_names"] == ["search_api_fulltext"]
    assert report["search_form_methods"] == ["get"]
    assert report["search_value_reflected"] is True
    assert report["declared_result_count"] == 24
    assert report["keyword_in_visible_text"] is False
    serialized = json.dumps(report)
    assert "private-secret" not in serialized
    assert "sensitive-form-value" not in serialized
    assert "someone@example.org" not in serialized
    assert "csrf" not in serialized
    assert "form_build_id" not in serialized


def test_search_form_absence_is_not_evidence_of_unsupported_query():
    report = search_page_evidence(
        "<html><h2>Search results (6,023)</h2></html>",
        "https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=keywords%3Aepigenetics",
    )
    assert report["search_input_names"] == []
    assert report["search_form_methods"] == []
    assert report["search_value_reflected"] is False
    assert report["declared_result_count"] == 6023


def test_different_form_input_value_cannot_verify_configured_keyword():
    report = search_page_evidence(
        '<form method="POST"><input type="text" name="keywords" '
        'placeholder="Search jobs" value="gene regulation"/></form>',
        "https://euraxess.ec.europa.eu/jobs/search?f%5B0%5D=keywords%3Aepigenetics",
    )
    assert report["search_input_names"] == ["keywords"]
    assert report["search_form_methods"] == ["post"]
    assert report["search_value_reflected"] is False
