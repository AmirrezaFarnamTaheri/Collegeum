"""Offline regressions for the 2026-11-01 cross-audience LinkedIn 429.

Search ledgers remain independent, but provider access limits cannot be
isolated by audience. All HTTP clients here are fakes/MockTransport.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from predoc_pipeline.boards.config import SourceConfig, load_board_sources
from predoc_pipeline.boards.http import FetchError, HttpClient
from predoc_pipeline.boards.scrapers.linkedin_scheduler import QueryLedger, query_key
from predoc_pipeline.boards.scrapers.linkedin_scraper import LinkedInScraper
from predoc_pipeline.ingest.life_sciences import load_life_sources

T0 = datetime(2026, 11, 1, 5, 50, 37, tzinfo=UTC)
ECON_PAIR = ("PhD quantitative social science", "Sweden")
LIFE_PAIR = ("PhD epigenetics", "European Union")


def cards() -> list[dict[str, str]]:
    return [
        {"id": str(4980001000 + i), "title": "PhD Molecular Biology", "company": "University"}
        for i in range(10)
    ]


class OfflineHTTP:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def set_host_interval(self, *_args: object) -> None:
        pass

    async def get_text(self, url: str, **_kwargs: object) -> str:
        self.urls.append(url)
        return (
            '<div class="base-card" data-entity-urn="urn:li:jobPosting:4980001999">'
            '<a href="https://www.linkedin.com/jobs/view/4980001999"></a>'
            '<h3>PhD Molecular Biology</h3></div>'
        )


def worker(
    name: str, checkpoint: Path, peer_name: str, peer_checkpoint: Path,
    http: OfflineHTTP, now: datetime,
) -> LinkedInScraper:
    cfg = SourceConfig(
        name=name, type="linkedin", keywords=["PhD epigenetics"],
        locations=["European Union"], query_budget=1, request_budget=1,
        time_budget_seconds=10, max_pages=4,
        checkpoint_path=str(checkpoint), peer_checkpoint_path=str(peer_checkpoint),
        peer_checkpoint_source=peer_name,
    )
    scraper = LinkedInScraper(cfg, http)
    scraper._scheduler_now = lambda: now
    return scraper


def test_econ_429_blocks_life_search_and_detail_without_losing_replay(tmp_path: Path) -> None:
    econ_path, life_path = tmp_path / "econ.json", tmp_path / "life.json"
    econ = QueryLedger("linkedin")
    econ.request(ECON_PAIR, now=T0)
    econ.fail(ECON_PAIR, now=T0, status=429)
    econ.save(econ_path)

    life = QueryLedger("life_linkedin")
    life.request(LIFE_PAIR, now=T0 - timedelta(hours=1))
    life.accept_page(LIFE_PAIR, cards(), now=T0 - timedelta(hours=1))
    life.save(life_path)
    before_econ = econ_path.read_bytes()

    http = OfflineHTTP()
    scraper = worker(
        "life_linkedin", life_path, "linkedin", econ_path,
        http, T0 + timedelta(minutes=4),
    )
    posts, count = asyncio.run(scraper.run())
    assert count == len(posts) == 10  # historical cards still replay
    assert http.urls == []  # no new search while another audience is limited
    assert scraper.search_diagnostics["requests"] == 0
    assert scraper.search_diagnostics["provider_cooldown_active"] is True
    assert scraper.search_diagnostics["access_blocked_until"] == (
        T0 + timedelta(hours=48)
    ).isoformat()
    assert asyncio.run(scraper.fetch_detail(posts[0])) is None
    assert http.urls == []
    scraper.mark_detail_attempt(posts[0])
    scraper.flush_checkpoint()
    persisted = QueryLedger.load(life_path, "life_linkedin")
    row = persisted.state["queries"][query_key("life_linkedin", *LIFE_PAIR)]
    assert row["pending"]["offset"] == 10
    assert row["last_complete_at"] is None
    assert "detail_last_attempt_at" not in persisted.state["spool"][posts[0].extra["linkedin_id"]]
    assert econ_path.read_bytes() == before_econ  # peer ledger is read-only


def test_life_403_blocks_economics_search_then_expires(tmp_path: Path) -> None:
    life_path, econ_path = tmp_path / "life.json", tmp_path / "econ.json"
    life = QueryLedger("life_linkedin")
    life.request(LIFE_PAIR, now=T0)
    life.fail(LIFE_PAIR, now=T0, status=403)
    life.save(life_path)

    http = OfflineHTTP()
    blocked = worker(
        "linkedin", econ_path, "life_linkedin", life_path,
        http, T0 + timedelta(hours=4),
    )
    asyncio.run(blocked.run())
    assert http.urls == []
    assert blocked.search_diagnostics["provider_cooldown_active"] is True

    after = worker(
        "linkedin", econ_path, "life_linkedin", life_path,
        http, T0 + timedelta(hours=49),
    )
    asyncio.run(after.run())
    assert len(http.urls) == 1
    assert after.search_diagnostics["provider_cooldown_active"] is False


def test_configured_economics_and_life_sources_share_access_blocks_not_cursors() -> None:
    root = Path(__file__).resolve().parents[2]
    econ = next(s for s in load_board_sources(root / "config/sources.toml")
                if s.name == "linkedin")
    life = next(s for s in load_life_sources(root / "config/life_sciences.toml")
                if s.name == "life_linkedin")
    assert econ.opt("peer_checkpoint_path") == life.opt("checkpoint_path")
    assert life.opt("peer_checkpoint_path") == econ.opt("checkpoint_path")
    assert econ.opt("peer_checkpoint_source") == life.name
    assert life.opt("peer_checkpoint_source") == econ.name
    assert econ.opt("checkpoint_path") != life.opt("checkpoint_path")


def test_detail_http_429_stops_without_user_agent_retry() -> None:
    attempts: list[int] = []

    def respond(_request: httpx.Request) -> httpx.Response:
        attempts.append(429)
        return httpx.Response(429, headers={"Retry-After": "60"})

    async def run() -> None:
        async with HttpClient(
            max_retries=3, backoff_base=0,
            default_min_interval=0,
            transport=httpx.MockTransport(respond),
        ) as http:
            cfg = SourceConfig(name="linkedin", type="linkedin")
            scraper = LinkedInScraper(cfg, http)
            post = scraper.make(
                title="PhD Economics", url="https://www.linkedin.com/jobs/view/4980001999",
                extra={"linkedin_id": "4980001999"},
            )
            with pytest.raises(FetchError) as error:
                await scraper.fetch_detail(post)
            assert error.value.status == 429

    asyncio.run(run())
    assert attempts == [429]
