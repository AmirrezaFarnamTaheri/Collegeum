"""Source discovery and clickable URL regressions from the PR 30 review."""

import asyncio
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import SourceConfig
from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper
from predoc_pipeline.core.urls import clean_url

TEMPLATE = '<a href="/job/%5Bnid%5D">Research Assistant in Economics</a>'
VACANCY = '<a href="/job/123">Research Assistant in Economics</a>'


class FixtureHttp:
    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    async def get_text(self, url):
        self.requests.append(url)
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return value


def _scraper(http, *urls, **options):
    return LinkScanScraper(SourceConfig(
        name="review", type="link_scan", urls=list(urls),
        link_pattern="/job/", max_pages=3, pagination_param="page",
        skip_unresolved_link_templates=True, **options,
    ), http)


def test_template_endpoint_does_not_hide_a_later_endpoint_with_real_jobs():
    http = FixtureHttp({
        "https://example.org/template": TEMPLATE,
        "https://example.org/working": VACANCY,
        "https://example.org/working?page=2": "<p>No more jobs</p>",
    })
    scraper = _scraper(http, "https://example.org/template", "https://example.org/working")
    result = asyncio.run(_scrape_all([scraper], 1, 5))[0]
    assert not result.skipped
    assert [post.url for post in result.posts] == ["https://example.org/job/123"]
    assert http.requests == list(http.pages)
    assert result.as_stats()["errors"] > 0  # The other endpoint remains incomplete.


@pytest.mark.parametrize("template_first", [False, True])
def test_template_skip_does_not_mask_a_failure_on_another_endpoint(template_first):
    pages = {
        "https://example.org/broken": RuntimeError("upstream unavailable"),
        "https://example.org/template": TEMPLATE,
    }
    urls = list(pages)
    if template_first:
        urls.reverse()
    http = FixtureHttp(pages)
    result = asyncio.run(_scrape_all([_scraper(http, *urls)], 1, 5))[0]
    assert not result.ok
    assert not result.skipped
    assert result.as_stats()["errors"] >= 1
    assert "fetch" in result.failure_stage
    assert http.requests == urls


@pytest.mark.parametrize("selectors", [None, {"item": "article", "link": "a", "title": "a"}])
def test_non_template_url_failures_are_not_treated_as_template_skips(selectors):
    url = "https://example.org/list"
    source = SourceConfig(
        name="review", type="link_scan", url=url, link_pattern="/job/",
        skip_unresolved_link_templates=True, selectors=selectors,
    )
    html = '<article><a href="https://login.microsoftonline.com/job/123">Research Assistant</a></article>'
    result = asyncio.run(_scrape_all([LinkScanScraper(source, FixtureHttp({url: html}))], 1, 5))[0]
    assert not result.skipped
    assert not result.ok
    assert result.failure_stage == "parse"


def test_mixed_template_and_invalid_links_are_reported_as_parser_failure():
    url = "https://example.org/list"
    source = SourceConfig(
        name="review", type="link_scan", url=url, link_pattern="/job/",
        skip_unresolved_link_templates=True,
    )
    html = TEMPLATE + '<a href="https://login.microsoftonline.com/job/123">Research Assistant</a>'
    result = asyncio.run(_scrape_all([LinkScanScraper(source, FixtureHttp({url: html}))], 1, 5))[0]
    assert not result.skipped
    assert not result.ok
    assert result.failure_stage == "parse"


def test_display_url_preserves_a_legal_question_mark_in_the_request_target():
    url = "https://example.org/apply?next=https://careers.example.org/job?id=123&signature=opaque"
    cleaned = clean_url(url)
    assert cleaned == url
    assert httpx.URL(cleaned).raw_path == httpx.URL(url).raw_path
    assert parse_qs(urlsplit(cleaned).query)["next"] == ["https://careers.example.org/job?id=123"]
