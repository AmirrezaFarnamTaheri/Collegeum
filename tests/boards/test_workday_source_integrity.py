"""Contract tests for Workday pagination completeness at live-observed source totals.

2026-10-28 GitHub Actions probe found 42 McGill finance results and 220
UChicago research-professional results, beyond the configured 40/60 limits.
Never silently lose job identities or call capped discovery successful.
"""

import asyncio
from math import ceil
from pathlib import Path

import pytest

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers.university_ats import WorkdayScraper


class WorkdayFixtureHttp:
    def __init__(self, term: str, total: int):
        self.term = term
        self.total = total
        self.offsets = []

    async def post_json(self, url, payload):
        assert url.endswith("/jobs")
        assert payload["limit"] == 20
        term, offset = payload["searchText"], payload["offset"]
        self.offsets.append((term, offset))
        count = min(20, max(self.total - offset, 0)) if term == self.term else 0
        batch = [
            {
                "title": "Research Professional" if term == "research professional"
                    else "Research Assistant, Finance",
                "externalPath": f"/job/Opportunity-{offset + i:04d}",
                "bulletFields": ["Research"],
                "locationsText": "Campus",
                "postedOn": "Posted Yesterday",
            }
            for i in range(count)
        ]
        return {"jobPostings": batch, "total": self.total if term == self.term else 0}


def _source(name):
    return next(
        cfg for cfg in load_board_sources(Path("config/sources.toml"))
        if cfg.name == name
    )


@pytest.mark.parametrize(("name", "term", "total"), [
    ("ubc", "research assistant finance", 36),
    ("mcgill", "research assistant finance", 42),
    ("uchicago_bfi", "research professional", 220),
])
def test_live_observed_search_results_are_not_truncated(name, term, total):
    source = _source(name)
    http = WorkdayFixtureHttp(term, total)
    result = asyncio.run(_scrape_all([WorkdayScraper(source, http)], 1, 20))[0]

    assert result.ok, (name, result.as_stats())
    assert result.as_stats()["failure_counts"] == {"fetch": 0, "parse": 0, "limit": 0}
    assert len(result.posts) == total
    assert len({post.url for post in result.posts}) == total
    offsets = [offset for search, offset in http.offsets if search == term]
    assert offsets == [page * 20 for page in range(ceil(total / 20))]
