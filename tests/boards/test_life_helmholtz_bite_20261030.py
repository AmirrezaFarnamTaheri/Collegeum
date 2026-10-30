"""Official Helmholtz Munich B-ite live-contract fixtures (2026-10-30).

The employer publishes an English and a German B-ite listing. Both use the
existing public B-ite search API, but share several job IDs. Never treat
navigation-only HTML, administrative roles or duplicate locale postings as
new Life Sciences doctoral opportunities.
"""
from __future__ import annotations

import asyncio
from datetime import date

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import HttpConfig
from predoc_pipeline.boards.scrapers.bite_jobs import BiteJobsScraper
from predoc_pipeline.ingest import life_sciences

API = "https://jobs.b-ite.com/api/v1/postings/search"
EN = (
    "https://cs-assets.b-ite.com/helmholtz-zentrum-muenchen/"
    "jobs-api/main-listing-en.js"
)
DE = (
    "https://cs-assets.b-ite.com/helmholtz-zentrum-muenchen/"
    "jobs-api/main-listing-de.js"
)
SITE = "https://www.helmholtz-munich.de/en/career/jobs"
GERMAN_SITE = "https://www.helmholtz-munich.de/karriere/stellenangebote"
HOST = "jobs.helmholtz-muenchen.de"
KEY = "a" * 40
PHD_ID = "8" * 40
ADMIN_ID = "f" * 40
STAFF_ID = "2" * 40


def source():
    sources = [
        s for s in life_sciences.load_life_sources("config/life_sciences.toml")
        if s.name == "life_special_de_helmholtz_munich"
    ]
    assert len(sources) == 1
    return sources[0]


def job(ident: str, title: str, *, until: str = "2026-11-30T22:59:00+00:00"):
    return {
        "id": ident, "title": title,
        "url": f"https://{HOST}/jobposting/{ident}",
        "startsOn": "2026-10-18T08:00:00+00:00",
        "endsOn": until,
        "custom": {
            "Zuordnung": ["Homepage_englisch", "Homepage_deutsch"],
            "place": ["Neuherberg near Munich"],
            "Institut": ["Institute for Diabetes and Obesity"],
            "Forschungsbereich": ["Cell Biology"],
        },
        "description": "<p>Doctoral research in molecular cell biology and proteomics.</p>",
    }


PHD = job(
    PHD_ID,
    "PhD Candidate (f/m/x) - Organelle Biology and Proteomics in Cardiometabolic Disease",
)
ADMIN = job(ADMIN_ID, "Assistenz der Institutsleitung (m/w/d)")
STAFF = job(STAFF_ID, "Feuerwehrtechniker:in (m/w/d)")


class FixtureHTTP:
    def __init__(self, *, en=None, de=None):
        self.en = list([ADMIN, PHD] if en is None else en)
        self.de = list([ADMIN, PHD, STAFF] if de is None else de)
        self.urls = []
        self.payloads = []

    def set_host_interval(self, url, delay):
        pass

    async def get_text(self, url):
        self.urls.append(url)
        assert url in (EN, DE)
        which = "main-listing-en" if url == EN else "main-listing-de"
        code = "Homepage_englisch" if url == EN else "Homepage_deutsch"
        locale = "en" if url == EN else "de"
        return (
            f'var apiKey = "{KEY}"; api("{which}", 0, "homepage", '
            f'"{code}", "{locale}", "styles");'
        )

    async def post_json(self, url, payload):
        assert url == API
        self.payloads.append(payload)
        assert payload["key"] == KEY
        assert payload["channel"] == 0
        assert payload["sort"] == {"by": "title", "order": "asc"}
        assert payload["filter"]["locale"] == {"in": ["en", "de"]}
        category = payload["filter"]["custom.Zuordnung"]["in"]
        assert category in (["Homepage_englisch"], ["Homepage_deutsch"])
        is_en = category == ["Homepage_englisch"]
        assert payload["locale"] == ("en" if is_en else "de")
        assert payload["origin"] == (SITE if is_en else GERMAN_SITE)
        rows = self.en if is_en else self.de
        off = payload["page"]["offset"]
        return {"jobPostings": rows[off:], "page": {
            "offset": off, "total": len(rows),
        }}


def test_existing_specialist_source_is_reused_and_activated_once():
    cfg = source()
    assert cfg.enabled is True
    assert cfg.type == "bite_jobs"
    assert cfg.opt("site_profile") == "helmholtz_munich"
    assert cfg.opt("widget_url") == EN
    assert cfg.opt("job_host") == HOST
    assert cfg.field_implied is False


def test_bilingual_api_reuses_official_site_urls_without_duplicate_job_ids():
    http = FixtureHTTP()
    result = asyncio.run(_scrape_all([BiteJobsScraper(source(), http)], 1, 30))[0]
    assert result.ok, result.as_stats()
    assert len(result.posts) == 3
    assert len({p.url for p in result.posts}) == 3
    assert {p.title for p in result.posts} == {
        PHD["title"], ADMIN["title"], STAFF["title"],
    }
    assert [p.deadline for p in result.posts] == [date(2026, 11, 30)] * 3
    assert all(p.country == "Germany" for p in result.posts)
    assert set(http.urls) == {EN, DE}
    assert len(http.payloads) == 2


def test_helmholtz_rejects_wrong_employer_domain_and_bad_job_identity():
    bad = job("a" * 40, "PhD Candidate in Molecular Biology")
    bad["url"] = "https://jobs.helmholtz-muenchen.de.evil.example/jobposting/" + "a" * 40
    wrong_id = job("b" * 40, "PhD Candidate in Genetics")
    wrong_id["url"] = f"https://{HOST}/jobposting/" + "c" * 40
    http = FixtureHTTP(en=[PHD, bad, wrong_id], de=[])
    result = asyncio.run(_scrape_all([BiteJobsScraper(source(), http)], 1, 30))[0]
    assert [p.url for p in result.posts] == [PHD["url"]]
    assert not result.ok
    assert result.as_stats()["failure_counts"]["parse"] >= 2


def test_life_sciences_classifies_real_phd_only_and_rejects_expired_and_staff():
    cfg = source()
    http = FixtureHTTP()
    posts, _ = asyncio.run(BiteJobsScraper(cfg, http).run())
    accepted = [
        life_sciences.classify_post(p, today=date(2026, 10, 30))
        for p in posts
    ]
    valid = [p for p in accepted if p is not None]
    assert len(valid) == 1
    assert valid[0]["title"] == PHD["title"]
    assert valid[0]["deadline"] == "2026-11-30"
    assert valid[0]["country"] == "Germany"
    assert valid[0]["url"] == PHD["url"]
    expired = job("d" * 40, PHD["title"], until="2026-10-01T22:59:00+00:00")
    late_http = FixtureHTTP(en=[expired], de=[])
    old_posts, _ = asyncio.run(BiteJobsScraper(cfg, late_http).run())
    assert len(old_posts) == 1
    assert life_sciences.classify_post(old_posts[0], today=date(2026, 10, 30)) is None


def test_life_discovery_accepts_supported_bite_adapter_and_records_real_work(
    monkeypatch,
):
    http = FixtureHTTP()
    class Context:
        async def __aenter__(self):
            return http

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(life_sciences, "build_http", lambda _cfg: Context())
    diagnostics = {}
    posts, errors = asyncio.run(life_sciences.discover(
        "config/life_sciences.toml", HttpConfig(),
        selected_names={"life_special_de_helmholtz_munich"},
        diagnostics=diagnostics,
    ))
    assert not errors
    assert len(posts) == 3
    assert diagnostics["life_special_de_helmholtz_munich"]["status"] == "discovered"
    assert diagnostics["life_special_de_helmholtz_munich"]["doctoral_candidates"] == 1


def test_bad_public_widget_fails_closed_instead_of_healthy_empty():
    cfg = source().model_copy(update={"widget_url": "https://attacker.invalid/jobs.js"})
    http = FixtureHTTP()
    result = asyncio.run(_scrape_all([BiteJobsScraper(cfg, http)], 1, 20))[0]
    assert not result.ok
    assert result.as_stats()["errors"] >= 1
    assert not http.payloads


def test_helmholtz_preserves_employer_place_institute_and_research_field():
    posts, _ = asyncio.run(BiteJobsScraper(source(), FixtureHTTP()).run())
    phd = next(p for p in posts if p.title == PHD["title"])
    assert phd.location == "Neuherberg near Munich"
    assert phd.department == "Institute for Diabetes and Obesity"
    assert phd.fields_of_research == "Cell Biology"


def test_explicitly_empty_bilingual_official_feed_is_verified_not_broken():
    scraper = BiteJobsScraper(source(), FixtureHTTP(en=[], de=[]))
    posts, _ = asyncio.run(scraper.run())
    assert posts == []
    assert scraper.verified_empty_evidence is True
    assert not scraper.discovery_fetch_errors
    assert not scraper.discovery_parse_errors


def test_failed_german_cohort_does_not_turn_empty_english_feed_into_success():
    class BrokenGerman(FixtureHTTP):
        async def get_text(self, url):
            if url == DE:
                raise RuntimeError("German recruitment widget unavailable")
            return await super().get_text(url)

    scraper = BiteJobsScraper(
        source(), BrokenGerman(en=[], de=[]),
    )
    posts, _ = asyncio.run(scraper.run())
    assert posts == []
    assert not getattr(scraper, "verified_empty_evidence", False)
    assert scraper.discovery_fetch_errors


def test_unverified_api_metadata_does_not_invent_location_or_research_field():
    malformed = job("d" * 40, PHD["title"])
    malformed["custom"] = {
        "place": ["Neuherberg", 99],
        "Institut": 12345,
        "Forschungsbereich": {"unknown": "Do not stringify"},
    }
    http = FixtureHTTP(en=[malformed], de=[])
    posts, _ = asyncio.run(BiteJobsScraper(source(), http).run())
    assert len(posts) == 1
    assert posts[0].location is None
    assert posts[0].department is None
    assert posts[0].fields_of_research is None
