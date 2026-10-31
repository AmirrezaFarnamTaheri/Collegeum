"""Robots policy and slow university outages must remain visible, bounded and cheap."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.ingest.career import poll_career
from predoc_pipeline.ingest.http import FetchResult


class ProviderClient:
    def __init__(self):
        self.calls: list[str] = []

    def get(self, url: str) -> FetchResult:
        self.calls.append(url)
        if "jobinja.ir" in url:
            return FetchResult(
                url=url, status=999, error="blocked by robots.txt"
            )
        return FetchResult(
            url=url, status=200,
            text='<a href="/en/job/data-analyst/12345">Data Analyst</a>',
        )


def _poll(tmp_path, client):
    journal = tmp_path / "career.ndjson"
    health = tmp_path / "career_health.json"
    added, errors = poll_career(
        journal, client=client, needs_iran=True,
        needs_remote=False, health_path=health, slot=7,
    )
    return added, errors, json.loads(health.read_text("utf-8"))


def test_first_jobinja_robots_denial_is_recorded_without_false_empty(tmp_path):
    client = ProviderClient()
    _, errors, report = _poll(tmp_path, client)

    source = report["sources"]["jobinja"]
    assert source["status"] == "blocked_robots"
    assert source["fetched"] == 1
    assert source["error_count"] == 1
    assert source["last_robots_denial_at"]
    assert any("robots.txt" in error for error in errors)
    assert sum("jobinja.ir" in url for url in client.calls) == 1


def test_recent_jobinja_robots_denial_suspends_retries_without_hiding_block(tmp_path):
    prior = {
        "sources": {
            "jobinja": {
                "status": "blocked_robots",
                "last_robots_denial_at": datetime.now(UTC).isoformat(),
                "last_success_at": "2026-10-22T04:36:01+00:00",
            }
        }
    }
    (tmp_path / "career_health.json").write_text(json.dumps(prior), encoding="utf-8")
    client = ProviderClient()
    _, errors, report = _poll(tmp_path, client)

    source = report["sources"]["jobinja"]
    assert source["status"] == "blocked_robots"
    assert source["fetched"] == 0
    assert source["last_success_at"] == "2026-10-22T04:36:01+00:00"
    assert source["last_robots_denial_at"] == prior["sources"]["jobinja"]["last_robots_denial_at"]
    assert not errors
    assert not any("jobinja.ir" in url for url in client.calls)
    assert any("irantalent.com" in url for url in client.calls)


def test_stale_jobinja_robots_denial_is_retried_for_recovery(tmp_path):
    prior = {
        "sources": {
            "jobinja": {
                "status": "blocked_robots",
                "last_robots_denial_at": (
                    datetime.now(UTC) - timedelta(hours=30)
                ).isoformat(),
            }
        }
    }
    (tmp_path / "career_health.json").write_text(json.dumps(prior), encoding="utf-8")
    client = ProviderClient()
    _, errors, report = _poll(tmp_path, client)

    assert sum("jobinja.ir" in url for url in client.calls) == 1
    assert report["sources"]["jobinja"]["status"] == "blocked_robots"
    assert report["sources"]["jobinja"]["fetched"] == 1
    assert any("robots.txt" in error for error in errors)


def test_mannheim_official_source_has_bounded_timeout():
    source = next(
        row for row in load_board_sources(Path("config/sources.toml"))
        if row.name == "mannheim_econ"
    )
    assert source.source_timeout_seconds is not None
    assert source.source_timeout_seconds <= 45
