"""Collector identity and partial-discovery diagnostics regression tests."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, patch

from predoc_pipeline.boards import collector
from predoc_pipeline.boards.config import Preferences, SourceConfig
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper


def test_distinct_same_title_institution_jobs_survive_cross_board_discovery():
    """PI, deadline and application URL differ: a title is not job identity."""
    prefs = Preferences()
    prefs.enrich.fetch_details = False
    prefs.filters.strong_terms = ["predoc"]
    prefs.filters.field_terms = ["economics"]
    configs = [
        SourceConfig(name=name, type="link_scan", url=f"https://example.org/{name}")
        for name in ("first", "second")
    ]
    posts = [
        JobPostSchema(
            title="Predoc in Economics", institution="Example University",
            source=name, url=f"https://example.org/job/{name}",
            deadline=date(2099, month, 1), pi_name=pi,
        )
        for name, month, pi in (
            ("first", 1, "Jane Doe"), ("second", 8, "Alan Smith"),
        )
    ]
    results = [
        collector.SourceResult(LinkScanScraper(config, None), [post])
        for config, post in zip(configs, posts, strict=True)
    ]
    with patch.object(collector, "_scrape_all", new=AsyncMock(return_value=results)):
        run = asyncio.run(collector._collect(configs, prefs, lambda _: False, None))
    assert {item.source_url for item in run.items} == {post.url for post in posts}
    assert run.rejected.get("duplicate-in-run", 0) == 0


def test_partial_link_scan_pagination_failure_is_reported_in_source_health():
    class OfflineHttp:
        async def get_text(self, url):
            if "page=2" in url:
                raise RuntimeError("second page unavailable")
            return '<a href="/job/1">Research Assistant in Economics</a>'

    scraper = LinkScanScraper(SourceConfig(
        name="partial", type="link_scan", url="https://example.org/jobs", max_pages=2,
        pagination_param="page", link_pattern="/job/",
    ), OfflineHttp())
    result = asyncio.run(collector._scrape_all([scraper], 1, 10))[0]
    health = result.as_stats()
    assert len(result.posts) == 1
    assert health["ok"] is False
    assert health["errors"] >= 1
    assert "fetch" in str(health["failure_stage"])
    assert health["messages"]


def test_link_scan_pagination_cap_is_visible_when_more_jobs_may_exist():
    class OfflineHttp:
        async def get_text(self, _url):
            return '<a href="/job/1">Research Assistant in Economics</a>'

    scraper = LinkScanScraper(SourceConfig(
        name="limited", type="link_scan", url="https://example.org/jobs", max_pages=2,
        pagination_param="page", link_pattern="/job/",
    ), OfflineHttp())
    result = asyncio.run(collector._scrape_all([scraper], 1, 10))[0]
    health = result.as_stats()
    assert len(result.posts) == 1  # URL deduplicated across two pages
    assert health["ok"] is False
    assert health["errors"] >= 1
    assert "limit" in str(health["failure_stage"])
