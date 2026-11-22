"""Provider HTTP 429 denials must never cause repeated or fallback Workday probes.

Offline regressions for main production #44994015596 (2026-11-22):
McGill and Chicago Workday returned 429 repeatedly despite explicit access limits.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import SourceConfig
from predoc_pipeline.boards.http import FetchError, HttpClient
from predoc_pipeline.boards.scrapers.university_ats import WorkdayScraper
from predoc_pipeline.core.health import source_status


def test_shared_board_http_rejects_429_once_by_default() -> None:
    """Do not rotate agents or retry even if Retry-After permits a quick retry."""
    requests: list[str] = []

    def responder(req: httpx.Request) -> httpx.Response:
        requests.append(str(req.url))
        return httpx.Response(429, headers={"Retry-After": "0"})

    async def run() -> None:
        async with HttpClient(
            max_retries=3, backoff_base=0, default_min_interval=0,
            transport=httpx.MockTransport(responder),
        ) as client:
            with pytest.raises(FetchError) as raised:
                await client.post_json(
                    "https://mcgill.wd3.myworkdayjobs.com/wday/cxs/mcgill/McGill_Careers/jobs",
                    {"searchText": "research assistant"},
                )
            assert raised.value.status == 429

    asyncio.run(run())
    assert len(requests) == 1


@pytest.mark.parametrize("denial_status", [403, 429])
def test_workday_does_not_probe_more_search_terms_after_access_denial(
    denial_status: int,
) -> None:
    """Preserve earlier results but never try a third term after a 403/429."""
    class DeniedWorkday:
        def __init__(self) -> None:
            self.terms: list[str] = []

        async def post_json(self, _url: str, payload: dict) -> dict:
            term = payload["searchText"]
            self.terms.append(term)
            if term == "research assistant finance":
                raise FetchError("HTTP provider access denied", status=denial_status)
            return {
                "jobPostings": [{
                    "title": "Predoctoral Research Assistant",
                    "externalPath": "/job/Research-Assistant_JR100",
                    "bulletFields": ["Research"],
                    "locationsText": "Campus",
                    "postedOn": "Posted Yesterday",
                }],
                "total": 1,
            }

    cfg = SourceConfig(
        name="mcgill", type="workday",
        url="https://mcgill.wd3.myworkdayjobs.com/McGill_Careers",
        search_terms=[
            "research assistant economics", "research assistant finance", "economics"
        ],
        institution="McGill University", country="Canada", max_pages=2,
    )
    http = DeniedWorkday()
    report = asyncio.run(_scrape_all([WorkdayScraper(cfg, http)], 1, 20))[0]
    assert http.terms == ["research assistant economics", "research assistant finance"]
    assert len(report.posts) == 1
    assert report.ok is False
    assert source_status(report.as_stats()) == "partial"
    assert report.as_stats()["failure_counts"]["fetch"] == 1


def test_shared_board_http_still_retries_transient_503() -> None:
    """The fail-closed 429 policy must not disable ordinary transient 503 recovery."""
    requests: list[int] = []

    def responder(_req: httpx.Request) -> httpx.Response:
        requests.append(1)
        if len(requests) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"jobPostings": []})

    async def run() -> None:
        async with HttpClient(
            max_retries=2, backoff_base=0, default_min_interval=0,
            transport=httpx.MockTransport(responder),
        ) as client:
            payload = await client.post_json(
                "https://mcgill.wd3.myworkdayjobs.com/wday/cxs/mcgill/McGill_Careers/jobs",
                {"searchText": "research assistant"},
            )
            assert payload == {"jobPostings": []}

    asyncio.run(run())
    assert len(requests) == 2
