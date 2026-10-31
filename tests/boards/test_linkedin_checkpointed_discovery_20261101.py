"""Black-box time-boxed LinkedIn search tests using a fake provider."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from predoc_pipeline.boards.config import SourceConfig
from predoc_pipeline.boards.http import FetchError
from predoc_pipeline.boards.scrapers.linkedin_scraper import LinkedInScraper
from predoc_pipeline.boards.scrapers.linkedin_scheduler import QueryLedger, query_key

T0 = datetime(2026, 11, 1, 8, tzinfo=UTC)


def page(start: int, count: int = 10) -> str:
    return "".join(
        f'<div class="base-card" data-entity-urn="urn:li:jobPosting:{5000000000 + start + i}">'
        f'<a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/{5000000000 + start + i}"></a>'
        "<h3 class='base-search-card__title'>PhD in Economics</h3>"
        "<h4 class='base-search-card__subtitle'>University</h4>"
        "</div>"
        for i in range(count)
    )


class FakeHTTP:
    def __init__(
        self, *, pages: dict[tuple[str, int], int] | None = None,
        fail_at: int | None = None,
    ) -> None:
        self.urls: list[str] = []
        self.pages = pages
        self.fail_at = fail_at

    def set_host_interval(self, *_args) -> None:
        return None

    async def get_text(self, url: str) -> str:
        self.urls.append(url)
        if self.fail_at == len(self.urls):
            raise FetchError("HTTP 429", status=429)
        args = parse_qs(urlsplit(url).query)
        term = args["keywords"][0]
        offset = int(args["start"][0])
        n = self.pages.get((term, offset), 0) if self.pages is not None else 10
        return page(offset, n)


def scraper(tmp_path: Path, http: FakeHTTP, *, budget: int = 2) -> LinkedInScraper:
    src = SourceConfig(
        name="linkedin", type="linkedin",
        keywords=["PhD economics", "predoc economics"],
        locations=["Germany"],
        query_budget=2, request_budget=budget,
        max_pages=12, time_budget_seconds=60,
        checkpoint_path=str(tmp_path / "search.json"),
        cooldown_hours=48,
    )
    result = LinkedInScraper(src, http)
    result._scheduler_now = lambda: T0
    return result


def test_first_run_publishes_partial_pages_and_next_run_resumes_offset(tmp_path) -> None:
    http = FakeHTTP(pages={
        ("PhD economics", 0): 10,
        ("predoc economics", 0): 10,
        ("PhD economics", 10): 1,
        ("predoc economics", 10): 1,
    })
    first = scraper(tmp_path, http)
    posts, n = asyncio.run(first.run())
    assert n == 10
    assert first.search_diagnostics["requests"] == 2
    assert first.search_diagnostics["pending_queries"] == 2
    assert (tmp_path / "search.json").exists()
    second = scraper(tmp_path, http, budget=3)
    second._scheduler_now = lambda: T0 + timedelta(hours=4)
    posts2, n2 = asyncio.run(second.run())
    assert n2 >= n
    assert any("start=10" in u for u in http.urls[2:])
    assert second.search_diagnostics["completed_queries"] == 2
    assert second.search_diagnostics["pending_queries"] == 0
    third = scraper(tmp_path, FakeHTTP())
    third._scheduler_now = lambda: T0 + timedelta(hours=32)
    _, _ = asyncio.run(third.run())
    assert third.search_diagnostics["requests"] == 0


def test_failure_after_first_page_replays_it_and_cursor_not_advanced(tmp_path) -> None:
    http = FakeHTTP(fail_at=2)
    first = scraper(tmp_path, http)
    posts, n = asyncio.run(first.run())
    assert n == 10
    assert first.search_diagnostics["access_limited"] is True
    state = QueryLedger.load(tmp_path / "search.json", "linkedin")
    assert len(state.items(now=T0)) == 10
    assert any(record.get("status") == "access_limited" for record in state.state["queries"].values())
    second = scraper(tmp_path, FakeHTTP())
    second._scheduler_now = lambda: T0 + timedelta(hours=4)
    posts2, _ = asyncio.run(second.run())
    assert len(posts2) >= 10
    assert not any(x.get("id") == "" for x in state.items(now=T0))


def test_repeated_query_on_day_three_uses_elapsed_time_plus_overlap(tmp_path) -> None:
    # After a completed scan, a same-day scan is suppressed. On day three
    # the provider request uses >=4-day lookback, not the last workflow slot.
    http = FakeHTTP(pages={("PhD economics", 0): 1, ("predoc economics", 0): 1})
    first = scraper(tmp_path, http)
    asyncio.run(first.run())
    later = scraper(tmp_path, FakeHTTP(pages={("PhD economics", 0): 1, ("predoc economics", 0): 1}))
    later._scheduler_now = lambda: T0 + timedelta(days=3)
    asyncio.run(later.run())
    assert later.search_diagnostics["requests"] == 2
    assert all("f_TPR=r604800" in u for u in later.http.urls)


def test_replay_stable_jobs_across_queries_and_fail_closed_corrupt_checkpoint(tmp_path) -> None:
    http = FakeHTTP()
    s = scraper(tmp_path, http)
    posts, _ = asyncio.run(s.run())
    assert len({p.url for p in posts}) == len(posts)
    source = QueryLedger.load(tmp_path / "search.json", "linkedin")
    assert source.state["queries"][query_key("linkedin", "PhD economics", "Germany")]["pending"]
    (tmp_path / "search.json").write_text("{", encoding="utf-8")
    broken = scraper(tmp_path, FakeHTTP())
    try:
        asyncio.run(broken.run())
    except Exception:
        pass
    else:
        raise AssertionError("Corrupt checkpoint must not be overwritten")
    assert (tmp_path / "search.json").read_text() == "{"
