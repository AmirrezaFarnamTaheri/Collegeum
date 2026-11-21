"""HTTP 200 access challenges must not become healthy PhD admission checks."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from tools.update_phd_admissions import (
    MAX_HTML_BYTES,
    check_official_url,
    investigate_official_pages,
)

NOW = datetime(2026, 11, 21, 15, tzinfo=UTC)
PAGE = "https://university.example.edu/phd"
ROBOTS = "https://university.example.edu/robots.txt"
POLICY = b"User-agent: *\nAllow: /\n"

BAD_HTML = [
    "<!doctype html><html><head><title>Just a moment...</title></head>"
    "<body>Checking your browser before accessing this site</body></html>",
    "<html><head><title>Access Denied</title></head>"
    "<body>Sorry, you have been blocked</body></html>",
    '<html><body><form id="challenge-form"><input name="cf_chl"></form></body></html>',
    '<html><body><div class="g-recaptcha" data-sitekey="site"></div></body></html>',
    "<html><head><title>Login Required</title></head>"
    "<body><form>Authentication required</form></body></html>",
    "<html><h1>Economics PhD Admissions</h1><p>Application deadline: "
    "15 January 2027.</p><div class='g-recaptcha'></div></html>",
    "<h1>Economics PhD Admissions</h1>"
    "<p>Application deadline: 15 January 2027.</p>"
    + " " * MAX_HTML_BYTES,
]


@pytest.mark.parametrize("html", BAD_HTML)
def test_official_admissions_production_checker_holds_http200_challenge(html):
    seen: list[str] = []

    def read(url: str, **_kwargs):
        seen.append(url)
        if url == ROBOTS:
            return 200, POLICY, url
        assert url == PAGE
        return 200, html.encode(), url

    with patch("tools.update_phd_admissions._read_url", side_effect=read):
        observation = check_official_url(PAGE, now=NOW)
    assert observation["status"] == "fetch_failed"
    assert observation["deadline_iso"] is None
    assert observation["investigated_urls"] == []
    assert seen == [ROBOTS, PAGE]


@pytest.mark.parametrize("html", BAD_HTML[:6])
def test_admissions_injected_official_page_cannot_bypass_response_validator(html):
    result = investigate_official_pages(
        PAGE, now=NOW, fetch_html=lambda _: (html, PAGE),
        robots_allowed=lambda _: True, max_pages=1,
    )
    assert result["status"] == "fetch_failed"
    assert result["investigated_urls"] == []
    assert result["deadline_iso"] is None


def test_ordinary_university_login_navigation_is_not_access_challenge():
    html = (
        "<!doctype html><html><head><title>PhD admissions</title></head>"
        "<body><nav><a href='/login'>Student login</a></nav>"
        "<h1>Economics PhD admissions</h1>"
        "<p>Application deadline: 15 January 2027.</p></body></html>"
    )
    observed = investigate_official_pages(
        PAGE, now=NOW, fetch_html=lambda _: (html, PAGE),
        robots_allowed=lambda _: True, max_pages=1,
    )
    assert observed["status"] == "verified"
    assert observed["deadline_iso"] == "2027-01-15"
    assert observed["investigated_urls"] == [PAGE]
