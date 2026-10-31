"""Regression fixtures from 2026-10-31 official University of Bern PhD adverts.

The employer's application instructions, not a bare Prospective end_date,
determine whether Collegeum can advertise a genuine closing deadline.
No network or production journal writes are performed in these tests.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest

from predoc_pipeline.boards.scrapers import SCRAPERS
from predoc_pipeline.ingest.life_sciences import classify_post
from tests.boards.test_bern_prospective_api_20261031 import FakeHttp, _config, _job, _page

BASE = "https://jobs.unibe.ch/job-vacancies/"
CANCER = BASE + (
    "phd-student-in-cancer-immunology-and-leukemia-stem-cell-biology/"
    "0a6853ac-d531-4ac1-bc57-592090585e19"
)
GENESIS_WET = BASE + (
    "phd-position-nccr-genesis-combining-remote-and-in-situ-life-detection-techniques/"
    "7e52c2be-b908-4dfd-b634-c72519d07262"
)
GENESIS_OPTICS = BASE + (
    "phd-position-nccr-genesis-remote-sensing-of-microorganisms-in-extreme-environments/"
    "a5825edd-e430-405e-a30e-935d10b872db"
)
BIOENERGY = BASE + (
    "phd-position-in-bottom-up-bioenergetics-and-cell-metabolism/"
    "8ba13379-21aa-4373-97ab-a4a8f1aac815"
)
MULTISENSORY = BASE + (
    "phd-position-in-multisensory-development/"
    "63cc79b4-88b8-4d0b-b4df-67ad952ed3de"
)
TRANSLATIONAL = BASE + (
    "phd-student-in-translational-cancer-research-snsf-project/"
    "49b665a5-4e94-4fb8-b005-3654ed74bd33"
)


def _parse(url: str, *, title: str, ends: str, application: str | None):
    job = _job(title=title, url=url, viewkey=url.rsplit("/", 1)[-1], deadline=ends)
    if application is not None:
        job["szas"]["sza_application"] = application
    scraper = SCRAPERS["prospective_jobs"](
        _config(), FakeHttp({0: _page(0, [job], 1)})
    )
    posts, count = asyncio.run(scraper.run())
    assert count == 1
    assert scraper.discovery_parse_errors == []
    return posts[0]


@pytest.mark.parametrize(
    ("url", "title", "ends", "application"),
    [
        (
            GENESIS_WET,
            "PhD position NCCR Genesis: combining remote and in-situ life detection techniques",
            "2026-12-31T22:59:59Z",
            "The review of the applications will start immediately and will continue "
            "until the position is filled.",
        ),
        (
            GENESIS_OPTICS,
            "PhD position NCCR Genesis: remote sensing of microorganisms in extreme environments",
            "2026-12-31T22:59:59Z",
            "The review of the applications will start immediately and will continue "
            "until the position is filled.",
        ),
        (
            MULTISENSORY,
            "PhD position in Multisensory Development",
            "2026-11-14T22:59:59Z",
            "Applications will be reviewed on a rolling basis until the position is filled.",
        ),
    ],
)
def test_rolling_recruitment_overrides_even_near_term_index_end(
    url: str, title: str, ends: str, application: str,
) -> None:
    post = _parse(url, title=title, ends=ends, application=application)
    assert post.deadline is None
    assert post.deadline_text == "Rolling until filled"
    assert post.extra["prospective_unverified_end_date"] == ends
    assert post.extra["require_deadline"] is True
    assert classify_post(post, today=date(2026, 10, 31)) is None


@pytest.mark.parametrize(
    ("url", "title", "ends", "application", "expected"),
    [
        (
            BIOENERGY, "PhD position in Bottom-up Bioenergetics and Cell Metabolism",
            "2026-11-20T22:59:59Z",
            "Application deadline: 20.11.2026. Submit CV and certificates online.",
            date(2026, 11, 20),
        ),
        (
            TRANSLATIONAL, "PhD Student in Translational Cancer Research, SNSF project",
            "2026-11-15T22:59:59Z",
            "Application deadline: 15.11.2026. Submit the usual documents.",
            date(2026, 11, 15),
        ),
    ],
)
def test_employer_corresponding_explicit_closing_date_remains_trusted(
    url: str, title: str, ends: str, application: str, expected: date,
) -> None:
    post = _parse(url, title=title, ends=ends, application=application)
    assert post.deadline == expected
    assert post.deadline_text is not None and "Official UniBE posting ends" in post.deadline_text
    assert "prospective_unverified_end_date" not in post.extra



def test_employer_review_excludes_physics_only_nccr_genesis_from_life_feed() -> None:
    post = _parse(
        GENESIS_OPTICS,
        title="PhD position NCCR Genesis: remote sensing of microorganisms in extreme environments",
        ends="2026-12-31T22:59:59Z",
        application="Application deadline: 31 December 2026.",
    )
    # An explicit physics/engineering MSc in the employer advert excludes
    # this particular opportunity from the biology-focused feed.
    assert classify_post(post, today=date(2026, 10, 31)) is None


def test_reviewed_exclusion_is_non_destructive_to_historical_journal(tmp_path) -> None:
    import json

    from predoc_pipeline.publish.subscriptions import matching
    from tools.export_life_sciences import stored_positions

    original = {
        "key": "career:historical-bern-optics",
        "category": "life_sciences_phd",
        "scope": "",
        "first_seen_at": "2026-10-31T19:55:26+00:00",
        "url": GENESIS_OPTICS,
        "title": "PhD position NCCR Genesis: remote sensing of microorganisms in extreme environments",
        "employer": "University of Bern",
        "location": "Bern, Switzerland",
        "source": "life_dach_bern",
        "funding_status": "unverified",
    }
    journal = tmp_path / "career_jobs.ndjson"
    saved = json.dumps(original) + "\n"
    journal.write_text(saved, encoding="utf-8")
    assert stored_positions(journal) == []
    member = {"topics": {"life_sciences_phd": "2026-10-01T00:00:00Z"}, "scopes": {}}
    assert matching(member, [], [original], preview=True) == []
    assert journal.read_text(encoding="utf-8") == saved
