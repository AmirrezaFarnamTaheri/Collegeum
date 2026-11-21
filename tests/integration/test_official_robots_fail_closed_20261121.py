"""Malformed robots responses must not silently allow official-source fetches."""
from __future__ import annotations

import urllib.robotparser
from unittest.mock import Mock, patch

import httpx
import pytest

from predoc_pipeline.ingest.http import PoliteClient
from tools.official_call_docx_review import fetch_reviewed_docx
from tools.official_call_pdf_review import fetch_reviewed_pdf
from tools.official_robots import parse_official_robots
from tools.update_official_calls import fetch_official
from tools.update_phd_admissions import check_official_url

PDF = "https://ieb.ub.edu/wp-content/uploads/2026/11/IEB-PhD-Scholarship-2027-28.pdf"
DOCX = "https://ieb.ub.edu/wp-content/uploads/2026/11/scholarship-2027.docx"
HTML = "https://ieb.ub.edu/en/phd-scholarship-in-economics-2027/"
SOURCE = {
    "id": "ieb-review", "institution": "Barcelona Institute of Economics (IEB)",
    "country_code": "ES", "mode": "index", "url": "https://ieb.ub.edu/convocatorias/",
    "approved_documents": [{
        "url": PDF, "title": "PhD Scholarship in Economics",
        "institution_marker": "Barcelona Institute of Economics",
        "canonical_html_url": HTML,
    }, {
        "url": DOCX, "title": "PhD Scholarship in Economics",
        "institution_marker": "Barcelona Institute of Economics",
        "canonical_html_url": HTML,
    }],
}


@pytest.mark.parametrize("blob", [
    b"<html><title>Challenge</title>Access restricted</html>",
    b'{"error":"login_required"}',
    b"User-agent: \nDisallow: /",
    b"Crawl-delay: 2\nSitemap: https://ieb.ub.edu/sitemap.xml",
    b"<!-- blocked --><html>Access denied</html>",
    b"User-agent: *\nDisallow: /\x00Allow: /",
    b"User-agent: *\nDisallow: /\xff",
    b"",
])
def test_shared_robots_validator_rejects_invalid_or_challenge_responses(blob):
    robot = urllib.robotparser.RobotFileParser()
    with pytest.raises(ValueError):
        parse_official_robots(blob, robot)


def test_crlf_and_inline_comments_remain_valid_robots_permissions():
    # Real institutional robots files use CRLF and inline comments; fail
    # closed only on malformed responses, not on normal syntax variants.
    robot = urllib.robotparser.RobotFileParser()
    parse_official_robots(
        b"User-Agent: * # all bots\r\nDisallow: /private\r\nAllow: /\r\n",
        robot,
    )
    assert not robot.can_fetch("CollegeumOfficialCalls/1.0", "https://ieb.ub.edu/private/x")
    assert robot.can_fetch("CollegeumOfficialCalls/1.0", HTML)


def test_shared_validator_honors_disallow_and_accepts_regular_rules():
    robot = urllib.robotparser.RobotFileParser()
    parse_official_robots(b"\xef\xbb\xbfUser-agent: *\nDisallow: /private\n", robot)
    assert not robot.can_fetch("CollegeumOfficialCalls/1.0", "https://ieb.ub.edu/private/a.pdf")
    assert robot.can_fetch("CollegeumOfficialCalls/1.0", HTML)


@pytest.mark.parametrize("review", ["pdf", "docx"])
def test_bad_robots_response_never_fetches_approved_document(review):
    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return b"<html><title>Maintenance</title></html>"

    opener = Mock()
    opener.open.return_value = Reply()
    with patch("urllib.request.build_opener", return_value=opener):
        got = (fetch_reviewed_pdf(PDF, SOURCE) if review == "pdf"
               else fetch_reviewed_docx(DOCX, SOURCE))
    assert got["status"] == "robots_unavailable"
    assert opener.open.call_count == 1


def test_official_html_discovery_rejects_challenge_robots_as_unknown_policy():
    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return "https://ieb.ub.edu/robots.txt"

        def read(self, limit):
            return b"<html>Sign in</html>"

    opener = Mock()
    opener.open.return_value = Reply()
    with patch("urllib.request.build_opener", return_value=opener):
        got = fetch_official(HTML)
    assert got["status"] == "robots_unavailable"
    assert opener.open.call_count == 1


@pytest.mark.parametrize("status,body,final", [
    (200, b"<html>Blocked</html>", "https://ieb.ub.edu/robots.txt"),
    (200, b"User-agent: *\nAllow: /\n", "https://ieb.ub.edu/other-robots.txt"),
    (401, b"User-agent: *\nAllow: /\n", "https://ieb.ub.edu/robots.txt"),
])
def test_official_programme_admissions_reject_invalid_robots(
    status, body, final,
):
    root = "https://ieb.ub.edu/robots.txt"
    with patch("tools.update_phd_admissions._read_url",
               return_value=(status, body, final)) as reader:
        from datetime import UTC, datetime

        got = check_official_url(HTML, now=datetime(2026, 11, 21, tzinfo=UTC))
    assert got["status"] == "robots_unavailable"
    reader.assert_called_once()


@pytest.mark.parametrize("policy", [
    b"<html>Please sign in</html>",
    b'{"status":"challenge"}',
    b"User-agent: *\nAllow: /\x00",
    b"User-agent: \nDisallow: /",
    b"",
])
def test_general_ingestion_polite_client_never_treats_challenge_as_robots_allow(policy):
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, content=policy)
        return httpx.Response(200, text="Unverified vacancy listing")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        crawler = PoliteClient(
            user_agent="CollegeumOfficialCalls/1.0", client=http,
            respect_robots=True, per_host_delay=0,
        )
        outcome = crawler.get("https://example.org/phd-scholarship",
                              sleep=lambda _: None)
    assert outcome.robots_blocked
    assert visited == ["https://example.org/robots.txt"]


def test_general_ingestion_polite_client_accepts_genuine_crlf_robots():
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200, content=b"User-agent: *\r\nDisallow: /private\r\n",
            )
        return httpx.Response(200, text="Public institutional listing")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        crawler = PoliteClient(
            user_agent="CollegeumOfficialCalls/1.0", client=http,
            respect_robots=True, per_host_delay=0,
        )
        allowed = crawler.get("https://example.org/public/phd",
                              sleep=lambda _: None)
        blocked = crawler.get("https://example.org/private/phd",
                              sleep=lambda _: None)
    assert allowed.ok
    assert blocked.robots_blocked
    assert visited == ["https://example.org/robots.txt", "https://example.org/public/phd"]
