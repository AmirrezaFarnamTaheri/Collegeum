"""Black-box time-boxed LinkedIn search tests using a fake provider."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from predoc_pipeline.boards.config import SourceConfig
from predoc_pipeline.boards.http import FetchError
from predoc_pipeline.boards.scrapers.linkedin_scheduler import QueryLedger, query_key
from predoc_pipeline.boards.scrapers.linkedin_scraper import LinkedInScraper

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

    async def get_text(self, url: str, **_options) -> str:
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
    # Fair replay emits the newly discovered card first; previously emitted
    # items remain in the durable spool for later retries if unresolved.
    assert n2 == 11
    assert "5000000010" in {p.extra["linkedin_id"] for p in posts2}
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



def test_soft_wall_clock_deadline_returns_observed_cards_and_saves_cursor(tmp_path) -> None:
    class SlowHTTP(FakeHTTP):
        async def get_text(self, url: str, **_options) -> str:
            await asyncio.sleep(0.65)
            return await super().get_text(url)

    http = SlowHTTP()
    src = SourceConfig(
        name="linkedin", type="linkedin",
        keywords=["PhD economics", "predoc economics"],
        locations=["Germany"], query_budget=2, request_budget=4,
        max_pages=12, time_budget_seconds=1,
        checkpoint_path=str(tmp_path / "slow.json"),
    )
    worker = LinkedInScraper(src, http)
    worker._scheduler_now = lambda: T0
    posts, n = asyncio.run(worker.run())
    assert 1 <= len(http.urls) <= 2
    assert n == 10 and len(posts) == 10
    assert worker.search_diagnostics["time_budget_reached"] is True
    state = QueryLedger.load(tmp_path / "slow.json", "linkedin")
    assert len(state.items(now=T0)) == 10
    assert sum(v["last_complete_at"] is not None for v in state.state["queries"].values()) == 0


def test_blank_guest_response_never_means_verified_no_vacancies(tmp_path) -> None:
    class BlankHTTP(FakeHTTP):
        async def get_text(self, url: str, **_options) -> str:
            self.urls.append(url)
            return ""

    worker = scraper(tmp_path, BlankHTTP())
    posts, n = asyncio.run(worker.run())
    assert posts == [] and n == 0
    assert worker.search_diagnostics["unverified_empty"] == 2
    assert worker.discovery_parse_errors == []
    state = QueryLedger.load(tmp_path / "search.json", "linkedin")
    assert not any(row["last_complete_at"] for row in state.state["queries"].values())



def test_seen_listing_checkpoint_is_acknowledged_before_new_requests(tmp_path) -> None:
    http = FakeHTTP(pages={("PhD economics", 0): 1, ("predoc economics", 0): 1})
    first = scraper(tmp_path, http)
    posts, count = asyncio.run(first.run())
    assert count == len(posts) == 1
    second = scraper(tmp_path, FakeHTTP())
    second._scheduler_now = lambda: T0 + timedelta(hours=4)
    second._known_url = lambda url: url == posts[0].url
    _, count2 = asyncio.run(second.run())
    assert count2 == 0
    assert second.search_diagnostics["acknowledged_seen"] == 1
    assert second.search_diagnostics["requests"] == 0


def test_rejected_card_removal_is_checkpointed_without_journal_mutation(tmp_path) -> None:
    http = FakeHTTP(pages={("PhD economics", 0): 1, ("predoc economics", 0): 1})
    worker = scraper(tmp_path, http)
    posts, count = asyncio.run(worker.run())
    assert count == 1
    worker.drop_filtered(posts[0])
    worker.flush_checkpoint()
    state = QueryLedger.load(tmp_path / "search.json", "linkedin")
    assert state.items(now=T0) == []
    assert state.counts()["acknowledged_filtered"] == 1



def test_unknown_nonempty_html_cannot_complete_query_or_advance_cursor(tmp_path) -> None:
    class InterstitialHTTP(FakeHTTP):
        async def get_text(self, url: str, **_options) -> str:
            self.urls.append(url)
            return "<html><body><h1>Temporary search unavailable</h1></body></html>"

    http = InterstitialHTTP()
    worker = scraper(tmp_path, http)
    posts, n = asyncio.run(worker.run())
    assert n == 0 and posts == []
    assert worker.search_diagnostics["unverified_empty"] == 2
    assert worker.discovery_parse_errors == []
    ledger = QueryLedger.load(tmp_path / "search.json", "linkedin")
    assert all(row["last_complete_at"] is None for row in ledger.state["queries"].values())
    assert ledger.plan(
        [("PhD economics", "Germany"), ("predoc economics", "Germany")],
        now=T0 + timedelta(hours=4), limit=2,
    ) == []


def test_unknown_followup_page_retains_previous_cards_and_offset(tmp_path) -> None:
    class PartialThenInterstitial(FakeHTTP):
        async def get_text(self, url: str, **_options) -> str:
            self.urls.append(url)
            offset = int(parse_qs(urlsplit(url).query)["start"][0])
            if offset:
                return "<html><body>Sorry, the results could not be loaded.</body></html>"
            return page(0)

    src = SourceConfig(
        name="linkedin", type="linkedin",
        keywords=["PhD economics"], locations=["Germany"],
        query_budget=1, request_budget=2,
        max_pages=12, time_budget_seconds=40,
        checkpoint_path=str(tmp_path / "partially-loaded.json"),
    )
    worker = LinkedInScraper(src, PartialThenInterstitial())
    worker._scheduler_now = lambda: T0
    posts, n = asyncio.run(worker.run())
    assert n == len(posts) == 10
    assert worker.search_diagnostics["unverified_empty"] == 1
    assert worker.discovery_parse_errors == []
    state = QueryLedger.load(tmp_path / "partially-loaded.json", "linkedin")
    row = state.state["queries"][query_key("linkedin", "PhD economics", "Germany")]
    assert row["pending"]["offset"] == 10
    assert row["last_complete_at"] is None
