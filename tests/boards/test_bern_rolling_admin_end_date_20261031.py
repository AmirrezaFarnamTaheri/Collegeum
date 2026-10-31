"""UniBE Prospective administrative end dates must not become application deadlines.

The official 2026-10-31 API returned several end_date values about ten
years after posting. The corresponding employer applications explain
"rolling until filled" or a first-review date, not a 2036 closing date.
"""
from __future__ import annotations

import asyncio
from datetime import date

from predoc_pipeline.boards.scrapers import SCRAPERS
from predoc_pipeline.ingest.life_sciences import classify_post
from tests.boards.test_bern_prospective_api_20261031 import FakeHttp, _config, _job, _page


def _parsed(*, posted: str, ends: str, application_text: str):
    job = _job(
        title="PhD Student Position in Cell Biology",
        deadline=ends,
    )
    job["start_date"] = posted
    job["szas"]["sza_application"] = application_text
    scraper = SCRAPERS["prospective_jobs"](
        _config(), FakeHttp({0: _page(0, [job], 1)})
    )
    posts, count = asyncio.run(scraper.run())
    assert count == 1
    assert scraper.discovery_parse_errors == []
    return posts[0]


def test_decade_administrative_end_date_is_not_a_rolling_application_deadline():
    post = _parsed(
        posted="2026-10-21T08:00:00Z",
        ends="2036-10-17T22:59:59Z",
        application_text=(
            "Applications will be reviewed on a rolling basis until "
            "the position is filled."
        ),
    )
    assert post.deadline is None
    assert post.deadline_text == "Rolling until filled"
    assert post.extra["prospective_unverified_end_date"] == "2036-10-17T22:59:59Z"
    assert classify_post(post, today=date(2026, 10, 31)) is None


def test_decade_administrative_end_date_with_no_rolling_text_is_still_unverified():
    post = _parsed(
        posted="2026-10-02T10:00:00Z",
        ends="2036-09-28T22:59:59Z",
        application_text="Please submit your application using the employer portal.",
    )
    assert post.deadline is None
    assert post.deadline_text == "Unverified employer-index end date"
    assert post.extra["prospective_unverified_end_date"] == "2036-09-28T22:59:59Z"
    assert classify_post(post, today=date(2026, 10, 31)) is None


def test_priority_review_date_is_not_implicitly_converted_to_hard_deadline():
    post = _parsed(
        posted="2026-10-15T09:00:00Z",
        ends="2036-10-12T22:59:59Z",
        application_text=(
            "Applications received by 30 November 2026 will receive "
            "full consideration. After the deadline, applications may "
            "continue to be reviewed until the position is filled."
        ),
    )
    assert post.deadline is None
    assert post.deadline_text == "Rolling until filled"
    assert post.extra["prospective_unverified_end_date"] == "2036-10-12T22:59:59Z"


def test_normal_official_end_date_remains_structured_and_published_as_before():
    post = _parsed(
        posted="2026-10-21T08:00:00Z",
        ends="2026-11-20T22:59:59Z",
        application_text="Applications close on 20 November 2026.",
    )
    assert post.deadline == date(2026, 11, 20)
    assert post.deadline_text.startswith("Employer-stated application deadline")
    assert "prospective_unverified_end_date" not in post.extra
    assert classify_post(post, today=date(2026, 10, 31)) is not None
