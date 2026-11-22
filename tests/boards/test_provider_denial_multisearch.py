"""Do not keep probing a provider after an explicit access denial.

Production run #44994015596 showed eight HTTP 200 access-interstitial
responses from jobs.ac.uk in a single ingestion cycle. These regressions
assert provider-safe stop behavior without hiding partial discoveries.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.http import FetchError
from predoc_pipeline.boards.scrapers import SCRAPERS
from predoc_pipeline.core.health import source_status


def _source():
    return next(
        cfg for cfg in load_board_sources(Path("config/sources.toml"))
        if cfg.name == "jobs_ac_uk"
    )


def test_access_interstitial_stops_all_remaining_search_urls():
    source = _source()
    assert len(source.opt("urls")) == 8

    class DeniedHttp:
        def __init__(self):
            self.urls = []

        async def get_text(self, url):
            self.urls.append(url)
            raise FetchError("access_interstitial", status=200)

    http = DeniedHttp()
    report = asyncio.run(_scrape_all([
        SCRAPERS[source.type](source, http)
    ], 1, 5))[0]

    assert http.urls == [source.opt("urls")[0]]
    assert report.posts == []
    assert report.ok is False
    assert report.as_stats()["failure_counts"]["fetch"] == 1
    assert source_status(report.as_stats()) == "failed"


def test_access_denial_preserves_earlier_results_but_not_later_queries():
    source = _source()
    urls = source.opt("urls")[:3]
    source = source.model_copy(update={"urls": urls})

    class PartialHttp:
        def __init__(self):
            self.urls = []

        async def get_text(self, url):
            self.urls.append(url)
            if url == urls[0]:
                return (
                    '<a href="https://www.jobs.ac.uk/job/DSY041/research-assistant">'
                    'Research Assistant in Economics</a>'
                )
            raise FetchError("access_interstitial", status=200)

    http = PartialHttp()
    report = asyncio.run(_scrape_all([
        SCRAPERS[source.type](source, http)
    ], 1, 5))[0]

    assert http.urls == urls[:2]
    assert [post.url for post in report.posts] == [
        "https://www.jobs.ac.uk/job/DSY041/research-assistant"
    ]
    assert report.ok is False
    assert report.as_stats()["failure_counts"]["fetch"] == 1
    assert source_status(report.as_stats()) == "partial"


@pytest.mark.parametrize("status", [403, 429])
def test_explicit_http_denial_stops_followup_query_urls(status):
    source = _source()
    urls = source.opt("urls")[:3]
    source = source.model_copy(update={"urls": urls})

    class DeniedHttp:
        def __init__(self):
            self.urls = []

        async def get_text(self, url):
            self.urls.append(url)
            raise FetchError(f"HTTP {status} denied", status=status)

    http = DeniedHttp()
    report = asyncio.run(_scrape_all([
        SCRAPERS[source.type](source, http)
    ], 1, 5))[0]

    assert http.urls == urls[:1]
    assert report.ok is False
    assert report.as_stats()["failure_counts"]["fetch"] == 1
    assert source_status(report.as_stats()) == "failed"


def test_transient_fetch_error_still_allows_next_query():
    source = _source()
    urls = source.opt("urls")[:2]
    source = source.model_copy(update={"urls": urls})

    class TemporaryFailureHttp:
        def __init__(self):
            self.urls = []

        async def get_text(self, url):
            self.urls.append(url)
            if url == urls[0]:
                raise FetchError("HTTP 503 temporary failure", status=503)
            return (
                '<a href="https://www.jobs.ac.uk/job/DSY041/research-assistant">'
                'Research Assistant in Economics</a>'
            )

    http = TemporaryFailureHttp()
    report = asyncio.run(_scrape_all([
        SCRAPERS[source.type](source, http)
    ], 1, 5))[0]

    assert http.urls == urls
    assert [post.url for post in report.posts] == [
        "https://www.jobs.ac.uk/job/DSY041/research-assistant"
    ]
    assert report.ok is False
    assert report.as_stats()["failure_counts"]["fetch"] == 1
    assert source_status(report.as_stats()) == "partial"
