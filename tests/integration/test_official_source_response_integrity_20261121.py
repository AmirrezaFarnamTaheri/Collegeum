"""Uniform official-source 200-response integrity across index and detail paths."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest

from predoc_pipeline.publish.official_calls import eligible_calls
from tools.update_official_calls import (
    MAX_HTML_BYTES,
    fetch_official,
    refresh_sources,
)

NOW = datetime(2026, 11, 21, 12, tzinfo=UTC)
INDEX = "https://ieb.ub.edu/en/news/"
DETAIL = "https://ieb.ub.edu/en/phd-scholarship-in-economics-2027/"
CONFIG = {
    "kind": "official_phd_call_sources", "version": 1,
    "sources": [{
        "id": "ieb-index", "institution": "Barcelona Institute of Economics (IEB)",
        "country_code": "ES", "mode": "index", "url": INDEX,
    }],
}
BEFORE = {
    "kind": "official_phd_call_observations", "version": 1,
    "sources": [], "calls": [],
}
CHALLENGES = (
    "<!doctype html><html><head><title>Just a moment...</title></head>"
    "<body>Checking your browser before accessing this site</body></html>",
    "<html><head><title>Access Denied</title></head>"
    "<body>Sorry, you have been blocked</body></html>",
    '<html><body><form id="challenge-form"><input name="cf_chl"></form></body></html>',
    '<html><body><div class="g-recaptcha" data-sitekey="site"></div></body></html>',
    "<html><head><title>Login Required</title></head>"
    "<body><form>Authentication required</form></body></html>",
)


@pytest.mark.parametrize("bad", [
    {"status": "ok"},
    {"status": "ok", "html": None},
    {"status": "ok", "html": 23},
    {"status": "ok", "html": "x" * (MAX_HTML_BYTES + 1)},
    {"status": "ok", "html": CHALLENGES[0]},
    {"status": "ok", "html": CHALLENGES[2]},
])
def test_success_response_without_usable_html_is_failed_not_empty(bad):
    catalog = refresh_sources(CONFIG, BEFORE, now=NOW, fetcher=lambda _: bad)
    row = catalog["sources"][0]
    assert row["status"] == "fetch_failed"
    assert row["index_empty"] is False
    assert row["html_index_empty"] is False
    assert row["unsupported_documents"] == 0
    assert not eligible_calls(catalog, now=NOW)


def test_invalid_success_response_is_held_for_direct_funding_calls():
    config = {**CONFIG, "sources": [
        {**CONFIG["sources"][0], "mode": "detail", "url": DETAIL}
    ]}
    got = refresh_sources(
        config, BEFORE, now=NOW,
        fetcher=lambda _: {"status": "ok", "html": "<title>403 Forbidden</title>"},
    )
    assert got["sources"][0]["status"] == "fetch_failed"
    assert got["calls"] == []


@pytest.mark.parametrize("html", CHALLENGES)
def test_html_challenge_returning_200_is_not_an_official_call_page(html):
    class Reply:
        def __init__(self, url, data):
            self.url = url
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, limit):
            return self.data[:limit]

        def geturl(self):
            return self.url

    opener = Mock()
    opener.open.side_effect = lambda request, timeout=9: Reply(
        request.full_url,
        (b"User-agent: *\nDisallow: \n" if request.full_url.endswith("/robots.txt")
         else html.encode("utf-8")),
    )
    with patch("urllib.request.build_opener", return_value=opener):
        result = fetch_official(DETAIL)
    assert result["status"] == "fetch_failed"
    assert opener.open.call_count == 2


def test_normal_official_html_can_have_login_links_without_being_blocked():
    real_index = (
        "<!doctype html><html><head><title>University PhD Scholarships</title></head>"
        '<body><nav><a href="/login">Student login</a></nav>'
        "<main><h2>PhD Scholarship in Economics 2027</h2></main></body></html>"
    )
    got = refresh_sources(
        CONFIG, BEFORE, now=NOW,
        fetcher=lambda _: {"status": "ok", "html": real_index},
    )
    assert got["sources"][0]["status"] == "ok"
    assert got["sources"][0]["html_index_empty"] is True
    assert got["sources"][0]["index_empty"] is True


def test_source_failure_does_not_keep_a_previous_verified_call_publishable():
    original = {
        "source_id": "ieb-index", "official_url": DETAIL,
        "status": "verified", "institution": "Barcelona Institute of Economics (IEB)",
        "country_code": "ES", "intake_year": 2027,
        "deadline_iso": "2026-12-11", "checked_at": "2026-11-21T10:00:00Z",
        "kind": "phd_scholarship",
    }
    previous = {**BEFORE, "calls": [original]}
    catalog = refresh_sources(
        CONFIG, previous, now=NOW,
        fetcher=lambda _: {"status": "ok", "html": CHALLENGES[1]},
    )
    assert catalog["sources"][0]["status"] == "fetch_failed"
    assert not eligible_calls(catalog, now=NOW)
    assert catalog["calls"][0]["status"] == "not_seen"
