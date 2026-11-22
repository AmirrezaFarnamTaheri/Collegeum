"""Regression cases for LinkedIn cooldown, durable verification and career alerts.

All provider HTTP is fake. Historical listing identities/receipts remain immutable.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from predoc_pipeline.boards.collector import check_links
from predoc_pipeline.boards.config import HttpConfig
from predoc_pipeline.boards.heuristics import check_still_open
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.publish.subscriptions import matching


def test_generic_link_checker_does_not_probe_linkedin_job_pages_during_cooldown():
    """Shared recheck must never bypass LinkedIn's restrictive access policy."""
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(999)

    verified = set()
    deferred = set()
    urls = {
        443: ("Postdoc", "https://www.linkedin.com/jobs/view/4489844974", None),
        444: ("Research associate", "https://linkedin.com/jobs/view/4484763054?trk=abc", None),
    }
    verdicts = check_links(
        urls, HttpConfig(max_retries=0, default_min_interval=0),
        transport=httpx.MockTransport(handler),
        verified_open=verified, skipped_provider=deferred,
    )
    assert verdicts == {443: None, 444: None}
    assert verified == set()
    assert deferred == {443, 444}
    assert requested == []


def test_generic_checker_still_verifies_official_employer_pages():
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, text="<html><body><h1>Research assistant in economics</h1></body></html>")

    verified = set()
    deferred = set()
    result = check_links(
        {1: ("Research assistant in economics", "https://university.example.edu/job/101", None)},
        HttpConfig(max_retries=0, default_min_interval=0),
        transport=httpx.MockTransport(handler),
        verified_open=verified, skipped_provider=deferred,
    )
    assert result == {1: None}
    assert verified == {1}
    assert deferred == set()
    assert requested == ["https://university.example.edu/job/101"]


def test_detail_absence_is_not_successful_open_verification():
    class Unreadable:
        async def fetch_detail(self, post):
            return None

    post = JobPostSchema(
        title="Research assistant", url="https://university.example.edu/jobs/1",
        source="recheck",
    )
    assert asyncio.run(check_still_open(Unreadable(), post)) is None
    assert not post.extra.get("recheck_reached")


def test_recheck_attempt_is_not_a_confirmed_open_verification(tmp_path):
    path = tmp_path / "positions.db"
    init(path)
    with Database(path) as db:
        db.conn.execute(
            "INSERT INTO listings (url_hash, apply_url, source_url, source, "
            "title, institution, first_seen_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("a" * 64, "https://www.linkedin.com/jobs/view/4489844974",
             "https://www.linkedin.com/jobs/view/4489844974", "linkedin",
             "Postdoc", "Example University", "2026-11-01T00:00:00Z",
             "2026-11-01T00:00:00Z"),
        )
        db.mark_checked(1)
        after_attempt = db.listing(1)
        assert after_attempt["last_checked_at"] is not None  # scheduling throttle
        assert after_attempt["last_verified_at"] is None      # no page was read
        db.mark_verified_open(1)
        accepted = db.listing(1)
        assert accepted["last_verified_at"] is not None
        assert accepted["last_checked_at"] is not None
        exported = db.export_rows()
        assert exported[0]["last_verified_at"] is not None

    restored = tmp_path / "restored.db"
    init(restored)
    with Database(restored) as db:
        db.import_rows(exported)
        assert db.listing(1)["last_verified_at"] == exported[0]["last_verified_at"]


@pytest.mark.parametrize("date_style", ["date", "instant"])
def test_expired_life_sciences_career_never_enters_private_match(date_style):
    now = datetime.now(UTC)
    def candidate(key: str, delta: int) -> dict[str, str]:
        deadline = now + timedelta(days=delta)
        value = (deadline.date().isoformat() if date_style == "date"
                 else deadline.isoformat())
        return {
            "key": "career:" + key, "category": "life_sciences_phd",
            "source": "life_linkedin", "scope": "",
            "title": "PhD researcher in genetics", "employer": "Example University",
            "url": "https://www.linkedin.com/jobs/view/" + key,
            "first_seen_at": (now - timedelta(hours=1)).isoformat(),
            "deadline": value, "availability": "unknown",
        }

    member = {"topics": {"life_sciences_phd": (now - timedelta(days=2)).isoformat()},
              "scopes": {}}
    rows = [candidate("1234500001", -2), candidate("1234500002", 7)]
    matches = matching(member, [], rows, preview=True)
    assert {r["key"] for r in matches} == {"career:1234500002"}
    assert rows[0]["deadline"] != ""


def test_today_date_only_career_deadline_remains_eligible():
    now = datetime.now(UTC)
    member = {"topics": {"life_sciences_phd": (now - timedelta(days=2)).isoformat()},
              "scopes": {}}
    row = {
        "key": "career:1234500003", "category": "life_sciences_phd",
        "source": "life_linkedin", "scope": "",
        "title": "PhD molecular biology", "employer": "Example University",
        "url": "https://www.linkedin.com/jobs/view/1234500003",
        "first_seen_at": (now - timedelta(hours=1)).isoformat(),
        "deadline": now.date().isoformat(), "availability": "unknown",
    }
    assert [r["key"] for r in matching(member, [], [row], preview=True)] == [row["key"]]
