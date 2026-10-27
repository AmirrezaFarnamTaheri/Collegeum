"""B-ite public career API regression tests grounded in ZEW's October 2026 widget."""

import asyncio
from datetime import date
from pathlib import Path

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import SourceConfig, load_board_sources
from predoc_pipeline.boards.scrapers.bite_jobs import BiteJobsScraper


KEY = "a" * 40
WIDGET = "https://cs-assets.b-ite.com/zew/jobs-api/mitarbeiter.js"
API = "https://jobs.b-ite.com/api/v1/postings/search"
ORIGIN = "https://www.zew.de/karriere/stellenangebote"


def posting(ident: str = "b" * 40, **changes):
    data = {
        "id": ident,
        "title": "Postdoctoral Researcher (100%, f/m/d)",
        "url": "https://jobs.zew.de/jobposting/" + ident + "0",
        "locale": "en",
        "startsOn": "2026-10-26T08:39:00+00:00",
        "endsOn": "2026-11-25T22:59:00+00:00",
        "custom": {"zuordnung_homepage": ["mitarbeiter"]},
    }
    data.update(changes)
    return data


class FixtureHttp:
    def __init__(self, pages, widget_key=KEY):
        self.pages = pages
        self.widget_key = widget_key
        self.offsets = []
        self.urls = []

    async def get_text(self, url):
        self.urls.append(("get", url))
        return 'var client = Api.createClient({ key: "' + self.widget_key + '" });'

    async def post_json(self, url, payload):
        self.urls.append(("post", url))
        assert payload["key"] == KEY
        assert payload["channel"] == 0
        assert payload["locale"] == "de"
        assert payload["filter"] == {
            "custom.zuordnung_homepage": {"in": ["mitarbeiter"]},
            "locale": {"in": ["*"]},
        }
        assert payload["origin"] == ORIGIN
        offset = payload["page"]["offset"]
        self.offsets.append(offset)
        return self.pages[offset]


def cfg():
    return SourceConfig(
        name="zew", type="bite_jobs", institution="ZEW Mannheim", country="Germany",
        field_implied=True, widget_url=WIDGET, api_url=API, origin=ORIGIN,
        category="mitarbeiter", max_pages=5,
    )


def test_zew_public_widget_yields_real_postdoc_and_doctoral_positions():
    first = posting("b" * 40)
    second = posting("c" * 40, title="Doctoral Researcher (f/m/d, 75%)",
                     endsOn="2026-11-11T22:59:00+00:00")
    http = FixtureHttp({0: {"jobPostings": [first, second], "page": {"offset": 0, "total": 2}}})
    result = asyncio.run(_scrape_all([BiteJobsScraper(cfg(), http)], 1, 10))[0]

    assert result.ok
    assert len(result.posts) == 2
    assert [p.url for p in result.posts] == [first["url"], second["url"]]
    assert result.posts[0].date_posted == date(2026, 10, 26)
    assert result.posts[0].deadline == date(2026, 11, 25)
    assert result.posts[0].institution == "ZEW Mannheim"
    assert result.posts[0].country == "Germany"
    assert result.as_stats()["raw"] == 2
    assert http.urls == [("get", WIDGET), ("post", API)]


def test_zew_api_paginates_using_server_reported_total():
    http = FixtureHttp({
        0: {"jobPostings": [posting("b" * 40), posting("c" * 40)],
            "page": {"offset": 0, "total": 3}},
        2: {"jobPostings": [posting("d" * 40)],
            "page": {"offset": 2, "total": 3}},
    })
    result = asyncio.run(_scrape_all([BiteJobsScraper(cfg(), http)], 1, 10))[0]
    assert result.ok and len(result.posts) == 3
    assert http.offsets == [0, 2]


def test_zew_drops_unsafe_urls_and_reports_malformed_entry_as_partial():
    good = posting("b" * 40)
    unsafe = posting("c" * 40, url="https://jobs.zew.de.evil.test/jobposting/" + "c" * 40)
    invalid = posting("d" * 40, title="")
    http = FixtureHttp({0: {
        "jobPostings": [good, unsafe, invalid], "page": {"offset": 0, "total": 3},
    }})
    result = asyncio.run(_scrape_all([BiteJobsScraper(cfg(), http)], 1, 10))[0]
    assert [p.url for p in result.posts] == [good["url"]]
    assert not result.ok
    assert result.as_stats()["failure_counts"]["parse"] == 2


def test_zew_unknown_public_widget_key_is_not_silent_empty():
    http = FixtureHttp({}, widget_key="not-a-public-client-key")
    result = asyncio.run(_scrape_all([BiteJobsScraper(cfg(), http)], 1, 10))[0]
    assert not result.ok
    assert result.as_stats()["errors"] >= 1
    assert http.offsets == []


def test_zew_production_uses_bite_jobs_api_without_headless_browser():
    source = next(s for s in load_board_sources(Path("config/sources.toml"))
                  if s.name == "zew")
    assert source.type == "bite_jobs"
    assert source.opt("widget_url") == WIDGET
    assert source.opt("api_url") == API
