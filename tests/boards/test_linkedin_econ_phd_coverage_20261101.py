"""Economics PhD discovery: bounded search-portfolio and diagnostic contracts.

No live requests, accounts, proxies or credentialed LinkedIn access.
This tests only the existing public-job discovery integration and its limits;
LinkedIn feed posts and employer-certified admissions remain separate.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from predoc_pipeline.boards.config import SourceConfig, load_board_sources
from predoc_pipeline.boards.http import FetchError
from predoc_pipeline.boards.scrapers.linkedin_scraper import (
    LinkedInScraper,
    build_search_plan,
)

ROOT = Path(__file__).resolve().parents[2]


def _catalogue() -> SourceConfig:
    return next(
        s for s in load_board_sources(ROOT / "config/sources.toml")
        if s.name == "linkedin"
    )


def test_portfolio_covers_doctoral_programme_and_research_job_language() -> None:
    cfg = _catalogue()
    keywords = cfg.opt("keywords")
    locations = cfg.opt("locations")
    assert len(keywords) >= 30
    assert len(locations) >= 10
    portfolio = " ".join(keywords).casefold()
    for phrase in (
        "predoc economics", "phd economics", "doctoral program",
        "phd studentship", "econometrics", "political economy",
        "doctoral researcher", "doktorand", "doctorant", "dottorato",
    ):
        assert phrase in portfolio
    assert "United States" in locations
    assert "European Union" in locations
    assert "United Kingdom" in locations
    assert "Canada" in locations
    assert len(cfg.opt("core_queries")) >= 4
    assert cfg.opt("request_budget") <= 30  # never multiply current request volume


def test_rotation_is_deterministic_budgeted_and_reaches_every_portfolio_pair() -> None:
    cfg = _catalogue()
    keywords, locations = cfg.opt("keywords"), cfg.opt("locations")
    core = [(x["keyword"], x["location"]) for x in cfg.opt("core_queries")]
    limit = cfg.opt("query_budget")
    pairs = {(kw, loc) for kw in keywords for loc in locations}
    assert len(pairs) >= 300
    assert all(len(build_search_plan(
        keywords, locations, core, slot=slot, query_budget=limit,
    )) <= limit for slot in range(25))
    seen: set[tuple[str, str]] = set()
    for slot in range(90):
        seen.update(build_search_plan(
            keywords, locations, core, slot=slot, query_budget=limit,
        ))
    assert pairs <= seen
    assert all(q in build_search_plan(
        keywords, locations, core, slot=7, query_budget=limit,
    ) for q in core)
    assert build_search_plan(
        keywords, locations, core, slot=4, query_budget=limit,
    ) == build_search_plan(
        keywords, locations, core, slot=4, query_budget=limit,
    )


def _cards(offset: int, *, count: int = 10, first_id: int = 4980000000) -> str:
    return "\n".join(
        '<div class="base-card" data-entity-urn="urn:li:jobPosting:{id}">'
        '<a class="base-card__full-link" '
        'href="https://www.linkedin.com/jobs/view/{id}"></a>'
        '<h3 class="base-search-card__title">PhD in Economics</h3>'
        '<h4 class="base-search-card__subtitle">University of Test City</h4>'
        '<span class="job-search-card__location">Germany</span>'
        '</div>'.format(id=first_id + offset + n)
        for n in range(count)
    )


class FakeHTTP:
    def __init__(self, *, block_at: int | None = None):
        self.calls: list[str] = []
        self.block_at = block_at

    def set_host_interval(self, *_a) -> None:
        return None

    async def get_text(self, url: str) -> str:
        self.calls.append(url)
        if self.block_at is not None and len(self.calls) == self.block_at:
            raise FetchError("HTTP 429", status=429)
        return _cards(int(parse_qs(urlsplit(url).query).get("start", ["0"])[0]))


def _test_scraper(http: FakeHTTP, **options) -> LinkedInScraper:
    return LinkedInScraper(
        SourceConfig(
            name="linkedin", type="linkedin", employer_required=True,
            keywords=["PhD economics", "doctoral program economics", "predoc economics"],
            locations=["Germany", "United Kingdom"],
            core_queries=[{"keyword": "PhD economics", "location": "Germany"}],
            query_budget=4,
            request_budget=6,
            query_slot=8,
            max_pages=2,
            **options,
        ),
        http,
    )


def test_fixed_request_ceiling_allows_some_second_page_discovery() -> None:
    http = FakeHTTP()
    scraper = _test_scraper(http)
    posts, count = asyncio.run(scraper.run())
    assert 0 < len(http.calls) <= 6
    assert any("start=10" in u for u in http.calls)
    assert len({x.url for x in posts}) == count
    assert scraper.search_diagnostics["requests"] == len(http.calls)
    assert scraper.search_diagnostics["plan_size"] == 4
    assert scraper.search_diagnostics["total_pairs"] == 6
    assert scraper.search_diagnostics["pages_with_more_possible"] >= 1
    assert all(x.url.startswith("https://www.linkedin.com/jobs/view/") for x in posts)


def test_rate_limit_stops_queue_and_records_partial_not_success() -> None:
    http = FakeHTTP(block_at=2)
    scraper = _test_scraper(http)
    posts, _ = asyncio.run(scraper.run())
    assert len(http.calls) == 2
    assert posts
    assert scraper.search_diagnostics["access_limited"] is True
    assert scraper.discovery_fetch_errors  # collector must report source partial
    assert scraper.search_diagnostics["requests"] == 2


def test_repeat_searches_keep_stable_identity_and_all_query_attributions() -> None:
    http = FakeHTTP()
    scraper = _test_scraper(http)
    posts, count = asyncio.run(scraper.run())
    assert count == len({p.url for p in posts})
    shared = next(x for x in posts if x.extra["linkedin_id"] == "4980000000")
    assert len(shared.extra["queries"]) >= 2
    assert shared.extra["query"] in shared.extra["queries"]


def test_slot_uses_utc_four_hour_schedule_not_random_order() -> None:
    cfg = _catalogue()
    # Same UTC slot remains stable across retries; next slot rotates.
    from predoc_pipeline.boards.scrapers.linkedin_scraper import utc_search_slot

    assert utc_search_slot(datetime(2026, 11, 1, 0, 1, tzinfo=UTC)) == (
        utc_search_slot(datetime(2026, 11, 1, 3, 59, tzinfo=UTC))
    )
    assert utc_search_slot(datetime(2026, 11, 1, 4, 1, tzinfo=UTC)) == (
        utc_search_slot(datetime(2026, 11, 1, 0, 1, tzinfo=UTC)) + 1
    )
    assert cfg.opt("f_TPR") == "r2592000"  # moving 30-day window for long-lead PhD calls
