"""EJM public advert-feed contract: explicit approval and safe stable identities."""
from __future__ import annotations

import asyncio
from datetime import date

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import SourceConfig
from predoc_pipeline.boards.scrapers import SCRAPERS

API = "https://backend.econjobmarket.org/data/zz_public/json/Ads"


class FixtureHttp:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    async def get_json(self, url, **kw):
        self.requests.append((url, kw))
        return self.payload


def source(*, approved=True, url=API):
    return SourceConfig(
        name="econjobmarket",
        type="econjobmarket_ads",
        url=url,
        redistribution_approved=approved,
        field_implied=True,
    )


def scrape(cfg, payload):
    transport = FixtureHttp(payload)
    result = asyncio.run(_scrape_all(
        [SCRAPERS[cfg.type](cfg, transport)], 1, 10,
    ))[0]
    return result, transport


def ad(**updates):
    item = {
        "adtitle": "Pre-Doctoral Research Assistant in Economics",
        "adtext": "<p>Work on macroeconomics and public policy.</p>",
        "name": "Example University",
        "department": "Economics",
        "url": "https://econjobmarket.org/positions/12951",
        "startdate": "2026-11-01",
        "deadline_date": "2026-12-15",
        "position_types": [{"name": "Research Assistant (Pre-Doc)"}],
        "categories": [{"name": "Economics"}],
    }
    return {**item, **updates}


def test_unapproved_feed_is_never_contacted():
    result, http = scrape(source(approved=False), [ad()])
    assert result.skipped is True
    assert result.posts == []
    assert http.requests == []


def test_official_feed_preserves_unique_job_url_and_source_facts():
    result, http = scrape(source(), [ad()])
    assert result.ok and not result.skipped
    assert len(result.posts) == 1
    post = result.posts[0]
    assert post.title == "Pre-Doctoral Research Assistant in Economics"
    assert post.url == "https://econjobmarket.org/positions/12951"
    assert post.institution == "Example University"
    assert post.department == "Economics"
    assert post.date_posted == date(2026, 11, 1)
    assert post.deadline == date(2026, 12, 15)
    assert post.fields_of_research == "Economics"
    assert "macroeconomics and public policy" in post.description_snippet.lower()
    assert http.requests[0][0] == API


def test_malformed_or_non_ejm_ad_is_partial_not_silently_healthy():
    result, _ = scrape(source(), [
        ad(),
        ad(url="https://econjobmarket.org.evil.example/positions/12952"),
        ad(url="https://econjobmarket.org/positions/[nid]"),
        ad(url="https://econjobmarket.org/positions/12953", deadline_date="tomorrow"),
    ])
    assert len(result.posts) == 1
    assert result.ok is False
    assert result.as_stats()["failure_counts"]["parse"] >= 1


def test_invalid_and_empty_feed_fail_closed():
    for payload in (None, {}, [], "login page", [123]):
        result, _ = scrape(source(), payload)
        assert result.ok is False, payload
        assert result.posts == []


def test_endpoint_cannot_be_replaced_with_an_unreviewed_host():
    result, http = scrape(
        source(url="https://unexpected.example/api"), [ad()],
    )
    assert not result.ok
    assert http.requests == []
