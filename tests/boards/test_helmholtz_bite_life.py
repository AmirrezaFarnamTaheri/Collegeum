"""Helmholtz Munich's official B-ite recruitment listing contract, 2026-10-30.

Live GitHub-runner probe 41061091332 confirmed a published 40-char client key,
10 German official jobposting identities, and distinct expiry dates. There
were no PhD titles that day; mixed-role staff must never turn into PhD alerts.
"""
from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pytest

from predoc_pipeline.boards.config import HttpConfig, SourceConfig
from predoc_pipeline.boards.scrapers.base import DiscoveryFetchError
from predoc_pipeline.boards.scrapers.bite_jobs import HelmholtzBiteScraper
from predoc_pipeline.ingest.life_sciences import classify_post, discover, load_life_sources

API = "https://jobs.b-ite.com/api/v1/postings/search"
URL = "https://www.helmholtz-munich.de/karriere/stellenangebote"
WIDGET = (
    "https://cs-assets.b-ite.com/helmholtz-zentrum-muenchen/"
    "jobs-api/main-listing-de.js"
)
KEY = "a" * 40
ID1, ID2, ID3 = "b" * 40, "c" * 40, "d" * 40


def cfg(**changes):
    opts = {
        "name": "life_special_de_helmholtz_munich",
        "type": "helmholtz_bite_jobs",
        "enabled": True,
        "group": "life_sciences",
        "country": "Germany",
        "institution": "Helmholtz Munich",
        "url": URL,
        "origin": URL,
        "widget_url": WIDGET,
        "api_url": API,
        "job_host": "jobs.helmholtz-muenchen.de",
        "max_pages": 3,
    }
    opts.update(changes)
    return SourceConfig(**opts)


def job(ident=ID1, **changes):
    row = {
        "id": ident, "title": "PhD Candidate (f/m/x) in Molecular Genetics",
        "url": "https://jobs.helmholtz-muenchen.de/jobposting/" + ident,
        "startsOn": "2026-10-20T12:00:00+00:00",
        "endsOn": "2026-11-20T22:59:00+00:00",
        "description": "<p>Doctoral research in genetics and molecular biology.</p>",
        "custom": {"place": ["Munich"], "category": ["Doctoral"]},
    }
    row.update(changes)
    return row


class FixtureHttp:
    def __init__(self, pages, *, script=None):
        self.pages = pages
        self.script = script if script is not None else (
            'var apiKey = "' + KEY + '";'
            'api("main-listing-de", 0, "public", "Homepage_deutsch", "de");'
        )
        self.calls = []

    async def get_text(self, url):
        self.calls.append(("GET", url))
        return self.script

    async def post_json(self, url, payload):
        self.calls.append(("POST", url, payload))
        assert url == API
        assert payload["key"] == KEY
        assert payload["channel"] == 0
        assert payload["locale"] == "de"
        assert payload["origin"] == URL
        assert payload["filter"] == {
            "locale": {"in": ["en", "de"]},
            "custom.Zuordnung": {"in": ["Homepage_deutsch"]},
        }
        return self.pages[payload["page"]["offset"]]


def run(pages, **kw):
    fake = FixtureHttp(pages, **kw)
    posts, _ = asyncio.run(HelmholtzBiteScraper(cfg(), fake).run())
    return posts, fake


def test_registry_reuses_disabled_specialist_source_with_official_verified_feed():
    source = next(s for s in load_life_sources(Path("config/life_sciences.toml"))
                  if s.name == "life_special_de_helmholtz_munich")
    assert source.enabled
    assert source.type == "helmholtz_bite_jobs"
    assert source.opt("widget_url") == WIDGET
    assert source.opt("origin") == URL
    assert source.opt("job_host") == "jobs.helmholtz-muenchen.de"
    assert source.country == "Germany"
    assert source.institution == "Helmholtz Munich"
    assert not source.field_implied


def test_public_search_finds_canonical_employer_url_and_accurate_deadline():
    rows = [job()]
    posts, fake = run({0: {"jobPostings": rows, "page": {"offset": 0, "total": 1}}})
    assert len(posts) == 1
    assert posts[0].url == rows[0]["url"]
    assert posts[0].deadline == date(2026, 11, 20)
    assert posts[0].date_posted == date(2026, 10, 20)
    assert posts[0].institution == "Helmholtz Munich"
    assert posts[0].country == "Germany"
    assert [c[0] for c in fake.calls] == ["GET", "POST"]
    assert fake.calls[0][1] == WIDGET
    assert classify_post(posts[0], today=date(2026, 10, 30)) is not None


def test_mixed_role_search_does_not_emit_student_or_senior_scientist_as_phd():
    rows = [
        job(ID1, title="Assistenz der Institutsleitung (m/w/d)"),
        job(ID2, title="Senior Scientist (f/m/x) in Metabolomics"),
        job(ID3, title="Student Assistant Core Facility Bioinformatics"),
    ]
    posts, _ = run({0: {"jobPostings": rows, "page": {"offset": 0, "total": 3}}})
    assert len(posts) == 3  # functioning index, not three doctoral vacancies
    assert all(classify_post(p, today=date(2026, 10, 30)) is None for p in posts)


def test_bounded_official_pagination_and_single_vacancy_identity():
    rows1 = [job(ID1), job(ID2)]
    rows2 = [job(ID3)]
    posts, fake = run({
        0: {"jobPostings": rows1, "page": {"offset": 0, "total": 3}},
        2: {"jobPostings": rows2, "page": {"offset": 2, "total": 3}},
    })
    assert [p.url for p in posts] == [row["url"] for row in rows1 + rows2]
    assert [call[2]["page"]["offset"] for call in fake.calls[1:]] == [0, 2]


def test_invalid_employer_hosts_and_mismatched_ids_are_rejected_as_parse_faults():
    correct = job()
    malicious = job(ID2, url="https://jobs.helmholtz-muenchen.de.evil.test/jobposting/" + ID2)
    wrong_id = job(ID3, url="https://jobs.helmholtz-muenchen.de/jobposting/" + ID2)
    fake = FixtureHttp({0: {
        "jobPostings": [correct, malicious, wrong_id],
        "page": {"offset": 0, "total": 3},
    }})
    scraper = HelmholtzBiteScraper(cfg(), fake)
    posts, _ = asyncio.run(scraper.run())
    assert [p.url for p in posts] == [correct["url"]]
    assert len(scraper.discovery_parse_errors) == 2


def test_widget_key_or_listing_contract_change_fails_closed():
    fake = FixtureHttp({}, script="window.someOtherWidget = true;")
    scraper = HelmholtzBiteScraper(cfg(), fake)
    with pytest.raises(DiscoveryFetchError):
        asyncio.run(scraper.run())
    assert not any(c[0] == "POST" for c in fake.calls)


def test_bad_pagination_is_not_a_healthy_empty_source():
    fake = FixtureHttp({0: {
        "jobPostings": [job()],
        "page": {"offset": 17, "total": 200},
    }})
    scraper = HelmholtzBiteScraper(cfg(), fake)
    posts, _ = asyncio.run(scraper.run())
    assert posts == []
    assert scraper.discovery_parse_errors


def test_source_rejects_untrusted_origin_configuration():
    fake = FixtureHttp({})
    scraper = HelmholtzBiteScraper(cfg(origin="https://example.org/evil"), fake)
    with pytest.raises(DiscoveryFetchError):
        asyncio.run(scraper.run())
    assert fake.calls == []



def test_official_empty_total_is_verified_empty_not_failed():
    fake = FixtureHttp({0: {"jobPostings": [], "page": {"offset": 0, "total": 0}}})
    scraper = HelmholtzBiteScraper(cfg(), fake)
    posts, _ = asyncio.run(scraper.run())
    assert posts == []
    assert scraper.verified_empty_evidence
    assert not scraper.discovery_parse_errors


def test_life_sciences_pipeline_accepts_official_adapter_without_publishing_staff(
    monkeypatch,
):
    from predoc_pipeline.ingest import life_sciences

    rows = [
        job(ID1, title="Senior Scientist (f/m/x) in Metabolomics"),
        job(ID2, title="Student Assistant in Bioinformatics"),
    ]
    fake = FixtureHttp({0: {"jobPostings": rows, "page": {"offset": 0, "total": 2}}})

    class ClientContext:
        async def __aenter__(self):
            return fake

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(life_sciences, "build_http", lambda _cfg: ClientContext())
    diagnostics = {}
    posts, errors = asyncio.run(discover(
        Path("config/life_sciences.toml"), HttpConfig(max_retries=0),
        selected_names={"life_special_de_helmholtz_munich"},
        diagnostics=diagnostics,
    ))
    assert not errors
    assert [p.url for p in posts] == [row["url"] for row in rows]
    assert diagnostics["life_special_de_helmholtz_munich"]["status"] == "discovered"
    assert diagnostics["life_special_de_helmholtz_munich"]["doctoral_candidates"] == 0
    assert all(classify_post(p, today=date(2026, 10, 30)) is None for p in posts)
