"""University of Bern official Prospective API: deterministic, employer-grounded contracts.

Live employer JavaScript advertises /public/v1/medium/1001892/jobs with offset,
limit and lang. Runner #41190504560 returned 62 total rows and 12 in the first
page. Regressions must fail before replacing the static HTML link scanner.
"""
from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from predoc_pipeline.boards.config import SourceConfig
from predoc_pipeline.boards.scrapers import SCRAPERS
from predoc_pipeline.ingest.life_sciences import classify_post, load_life_sources

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://ohws.prospective.ch/public/v1/medium/1001892/jobs"
LANDING = "https://karriere.unibe.ch/offene_stellen/index_ger.html"
VIEWKEY = "0a6853ac-d531-4ac1-bc57-592090585e19"
PHD_URL = (
    "https://jobs.unibe.ch/job-vacancies/"
    "phd-student-in-cancer-immunology-and-leukemia-stem-cell-biology/"
    + VIEWKEY
)


class FakeHttp:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def set_host_interval(self, *_args):
        return None

    async def get_json(self, url):
        self.calls.append(url)
        offset = int(url.split("offset=")[1].split("&")[0])
        return self.responses[offset]


def _config():
    return SourceConfig(
        name="life_dach_bern",
        type="prospective_jobs",
        group="life_sciences",
        url=LANDING,
        api_url=BASE,
        institution="University of Bern",
        country="Switzerland",
        max_pages=8,
        min_interval=3.0,
    )


def _job(title="PhD Student in Cancer Immunology and Leukemia Stem Cell Biology",
         url=PHD_URL, viewkey=VIEWKEY, deadline="2026-11-20T22:59:59Z"):
    return {
        "id": "10242812",
        "hk_id": "1005871",
        "viewkey": viewkey,
        "title": title,
        "language": "en",
        "links": {"directlink": url},
        "start_date": "2026-10-30T15:20:09Z",
        "end_date": deadline,
        "attributes": {
            "70": ["Faculty of Medicine"],
            "70_1160493": ["Department of Immunology"],
        },
        "szas": {
            "sza_location.country": "Switzerland",
            "sza_location.city": "Bern",
            "sza_requirements": (
                "Applicants need a Master's degree in molecular biology "
                "and expertise in cell biology."
            ),
            "sza_tasks": (
                "<p>Doctoral research on leukemia stem cells, cancer "
                "immunology and gene regulation.</p>"
            ),
        },
    }


def _page(offset, jobs, total):
    return {
        "medium_id": 1001892,
        "medium_name": None,
        "offset": offset,
        "total": total,
        "jobs": jobs,
        "filtercount": None,
    }


def test_current_bern_registry_uses_public_prospective_api():
    bern = next(
        source for source in load_life_sources(ROOT / "config/life_sciences.toml")
        if source.name == "life_dach_bern"
    )
    assert bern.enabled
    assert bern.type == "prospective_jobs"
    assert bern.opt("api_url") == BASE
    assert bern.opt("max_pages") >= 6


def test_bounded_public_api_preserves_real_employer_identity_and_deadline():
    staff = _job(
        title="Administrative Officer",
        url=("https://jobs.unibe.ch/job-vacancies/administrative-officer/"
             "c5eefb95-70e2-43a8-b681-0c3724329fdc"),
        viewkey="c5eefb95-70e2-43a8-b681-0c3724329fdc",
    )
    dated = _job()
    dated["szas"]["sza_application"] = "Applications close on 20 November 2026."
    http = FakeHttp({0: _page(0, [dated, staff], 2)})
    scraper = SCRAPERS["prospective_jobs"](_config(), http)
    posts, count = asyncio.run(scraper.run())
    assert count == 2
    assert http.calls == [BASE + "?offset=0&limit=12&lang=en"]
    phd = next(post for post in posts if post.title.startswith("PhD"))
    assert phd.url == PHD_URL
    assert phd.deadline == date(2026, 11, 20)
    assert phd.date_posted == date(2026, 10, 30)
    assert phd.country == "Switzerland"
    assert phd.location == "Bern, Switzerland"
    assert phd.department == "Department of Immunology"
    assert "gene regulation" in phd.description_snippet
    assert phd.extra["prospective_id"] == "10242812"
    match = classify_post(phd, today=date(2026, 10, 31))
    assert match is not None
    assert match["country"] == "Switzerland"
    assert match["deadline"] == "2026-11-20"


def test_two_real_api_pages_not_confused_with_one_empty_season():
    first = [_job()] + [
        _job(
            title=f"Technician {i}",
            url=(f"https://jobs.unibe.ch/job-vacancies/technician-{i}/"
                 f"1c6853ac-d531-4ac1-bc57-{i:012d}"),
            viewkey=f"1c6853ac-d531-4ac1-bc57-{i:012d}",
        ) for i in range(11)
    ]
    extra = _job(
        title="PhD Position in Epigenetics",
        url=("https://jobs.unibe.ch/job-vacancies/phd-position-in-epigenetics/"
             "2b6853ac-d531-4ac1-bc57-592090585e19"),
        viewkey="2b6853ac-d531-4ac1-bc57-592090585e19",
    )
    http = FakeHttp({0: _page(0, first, 13), 12: _page(12, [extra], 13)})
    scraper = SCRAPERS["prospective_jobs"](_config(), http)
    rows, count = asyncio.run(scraper.run())
    assert count == 13
    assert len(http.calls) == 2
    assert not scraper.discovery_parse_errors
    assert not scraper.discovery_limits
    assert not scraper.verified_empty_evidence


def test_malformed_next_page_proves_partial_discovery():
    http = FakeHttp({
        0: _page(0, [_job()], 2),
        1: _page(99, [_job()], 2),
    })
    scraper = SCRAPERS["prospective_jobs"](_config(), http)
    rows, _ = asyncio.run(scraper.run())
    assert len(rows) == 1
    assert scraper.discovery_parse_errors
    assert not scraper.verified_empty_evidence


def test_official_zero_total_is_healthy_empty_only_when_metadata_agrees():
    scraper = SCRAPERS["prospective_jobs"](
        _config(), FakeHttp({0: _page(0, [], 0)})
    )
    rows, _ = asyncio.run(scraper.run())
    assert rows == []
    assert scraper.verified_empty_evidence
    assert not scraper.discovery_parse_errors


def test_fake_host_or_job_viewkey_mismatch_cannot_make_a_vacancy():
    tampered = _job(
        url=PHD_URL.replace("jobs.unibe.ch", "jobs.unibe.ch.attacker.example"),
        viewkey="aaaa53ac-d531-4ac1-bc57-592090585e19",
    )
    mismatch = _job(viewkey="ffffffff-ffff-ffff-ffff-ffffffffffff")
    scraper = SCRAPERS["prospective_jobs"](
        _config(), FakeHttp({0: _page(0, [tampered, mismatch, _job()], 3)})
    )
    rows, _ = asyncio.run(scraper.run())
    assert len(rows) == 1
    assert rows[0].url == PHD_URL
    assert scraper.discovery_parse_errors

def test_far_future_official_end_date_is_not_assumed_a_real_application_deadline():
    # Observed on the real UniBE feed in #41190860083: one cell-biology
    # advert claims a 2036 close. Do not advertise a ten-year application window.
    candidate = _job(
        title="PhD Student Position in Cell Biology",
        deadline="2036-10-17T22:59:59Z",
    )
    scraper = SCRAPERS["prospective_jobs"](
        _config(), FakeHttp({0: _page(0, [candidate], 1)})
    )
    rows, _ = asyncio.run(scraper.run())
    assert len(rows) == 1
    assert rows[0].deadline is None
    assert rows[0].deadline_text == "Unverified employer-index end date"
    assert rows[0].extra["prospective_unverified_end_date"] == "2036-10-17T22:59:59Z"
    assert classify_post(rows[0], today=date(2026, 10, 31)) is None

    standard = _job(deadline="2027-10-17T22:59:59Z")
    standard["szas"]["sza_application"] = "Applications close on 17 October 2027."
    scraper = SCRAPERS["prospective_jobs"](
        _config(), FakeHttp({0: _page(0, [standard], 1)})
    )
    rows, _ = asyncio.run(scraper.run())
    assert len(rows) == 1
    assert classify_post(rows[0], today=date(2026, 10, 31)) is not None
