"""Quota shutdown must preserve completed work and health must reflect failures."""

import json
import threading
import time
from pathlib import Path

import pytest

from predoc_pipeline import pipeline, state
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.ratelimit import QuotaExceeded
from predoc_pipeline.extract import RateLimited
from predoc_pipeline.models import ExtractionResult, RawItem
from predoc_pipeline.settings import Settings


@pytest.fixture
def isolated_run(tmp_path, monkeypatch):
    sources = tmp_path / "sources.toml"
    sources.write_text("", encoding="utf-8")
    settings = Settings(
        _env_file=None, sources_config=str(sources),
        preferences_config="config/preferences.toml",
        db_path=str(tmp_path / "test.db"), state_path=str(tmp_path / "listings.ndjson"),
        seen_state_path=str(tmp_path / "seen.ndjson"),
        health_json=str(tmp_path / "health.json"),
        dashboard_json=str(tmp_path / "listings.json"), feed_path=str(tmp_path / "feed.xml"),
        feedback_path=str(tmp_path / "feedback.json"), dlq_path=str(tmp_path / "dlq.json"),
        telegram_bot_token="", telegram_public_channel_id="",
        extraction_concurrency=3, confidence_threshold=0.5,
    )
    monkeypatch.setattr(pipeline, "_verify_before_sending", lambda rows, *args: rows)
    monkeypatch.setattr(pipeline, "_recheck_published", lambda *args: None)
    monkeypatch.setattr(pipeline, "_maybe_alert", lambda *args: None)
    return settings


@pytest.mark.parametrize("item_count", [3, 7])
@pytest.mark.parametrize("failure", [QuotaExceeded("spent"), RateLimited("slow"),
                                     RuntimeError("invalid response")])
def test_concurrent_failure_drains_successful_inflight_results(
    isolated_run, monkeypatch, failure, item_count,
):
    barrier = threading.Barrier(3)
    started = set()
    items = [RawItem(
        source="test", source_url=f"https://example.org/job/{i}",
        title="Research Assistant in Economics",
        text="We are hiring a paid research assistant in economics. Apply now. "
             "Research in applied microeconomics and causal inference using Stata.",
        hints={"board": True},
    ) for i in range(item_count)]

    class Extractor:
        calls = 3

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract(self, *, source_url, **kwargs):
            started.add(source_url)
            if int(source_url.rsplit("/", 1)[1]) > 2:
                raise failure
            barrier.wait(timeout=3)
            if source_url.endswith("/0"):
                raise failure
            time.sleep(0.08)  # quota result is delivered before either success
            return ExtractionResult(
                is_vacancy=True, title="Research Assistant in Economics",
                institution="University of Oxford" if source_url.endswith("/1")
                            else "University of Cambridge",
                country="United States", application_url=source_url,
                summary="Paid research in applied microeconomics and causal inference.",
                disciplines=["Applied Microeconomics"], confidence=0.99,
            )

    monkeypatch.setattr(pipeline, "gather", lambda *args, **kwargs: (items, {}))
    monkeypatch.setattr(pipeline, "build_extractor", lambda *args, **kwargs: Extractor())
    stats = pipeline.run(isolated_run, sync_telegram=False)
    assert stats.extracted == stats.published == 2
    assert stats.quota_stopped is isinstance(failure, (QuotaExceeded, RateLimited))
    assert stats.errors == (0 if stats.quota_stopped else item_count - 2)
    if stats.quota_stopped:
        assert "https://example.org/job/6" not in started
    with Database(isolated_run.db_path) as db:
        assert {row["apply_url"] for row in db.export_rows()} == {
            "https://example.org/job/1", "https://example.org/job/2"
        }
    records = state.read_journal(isolated_run.state_path)
    assert len(records) == 2 and all(row["status"] == "published" for row in records)


def test_failed_sources_degrade_run_without_inventing_item_errors(isolated_run, monkeypatch):
    sources = {
        "board:working": {"ok": True, "items": 2, "fetched": 1},
        "board:empty": {"ok": True, "items": 0, "fetched": 1, "may_be_empty": True},
        "board:broken": {"ok": False, "items": 0, "errors": 1},
        "board:partial": {"items": 2, "errors": 1, "fetched": 1},
        "board:skipped": {"skipped": True, "items": 0},
        "_boards": {"kind": "summary", "deferred": 3},
    }
    monkeypatch.setattr(pipeline, "gather", lambda *args, **kwargs: ([], sources))
    stats = pipeline.run(isolated_run, sync_telegram=False)
    assert stats.outcome == "partial" and stats.errors == 0
    assert stats.source_errors == 2
    assert stats.sources == {"total": 5, "successful": 1, "empty": 1,
                             "failed": 2, "partial": 1, "skipped": 1}
    health = json.loads(Path(isolated_run.health_json).read_text(encoding="utf-8"))
    assert health["status"] == "degraded"
    assert health["source_summary"] == stats.sources


def test_health_preserves_last_success_and_redacts_failure_details(tmp_path):
    db_path = tmp_path / "test.db"
    init(db_path)
    with Database(db_path) as db:
        earlier = db.start_run("earlier")
        db.finish_run(earlier, {"outcome": "ok"}, {
            "board:test": {"ok": True, "fetched": 1, "items": 0, "may_be_empty": True}
        })
        success_at = db.recent_runs()[0]["finished_at"]
        recent = db.start_run("recent")
        db.finish_run(recent, {"outcome": "partial"}, {
            "board:test": {"ok": False, "errors": 1, "messages": [
                "HTTP 403 https://alice:password@example.org/jobs?token=secret Bearer abcdef"
            ]}
        })
        target = tmp_path / "health.json"
        state.export_health(db, target, stats={"outcome": "partial"})
    output = target.read_text(encoding="utf-8")
    assert all(secret not in output for secret in ("password", "secret", "abcdef", "alice"))
    health = json.loads(output)
    source = health["sources"]["board:test"]
    assert source["last_successful_at"] == success_at
    assert source["status"] == "failed" and source["messages"] == ["HTTP 403"]
    assert health["runs"][0]["source_stats"]["board:test"]["messages"] == ["HTTP 403"]


def test_fresh_fatal_health_is_never_ok(tmp_path):
    path = tmp_path / "db"
    init(path)
    with Database(path) as db:
        row = db.start_run("fatal")
        db.finish_run(row, {"outcome": "fatal"}, {})
        state.export_health(db, tmp_path / "health.json", stats={"outcome": "fatal"})
    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["status"] == "fatal"


def test_last_success_survives_rolling_history_limit(tmp_path):
    path = tmp_path / "db"
    init(path)
    health_path = tmp_path / "health.json"
    with Database(path) as db:
        row = db.start_run("successful")
        db.finish_run(row, {"outcome": "ok"}, {
            "board:test": {"ok": True, "fetched": 1, "items": 2}
        })
        state.export_health(db, health_path, stats={"outcome": "ok"})
        success = json.loads(health_path.read_text(encoding="utf-8"))["last_successful_run_at"]
        for i in range(31):
            row = db.start_run(f"failed-{i}")
            db.finish_run(row, {"outcome": "partial"}, {
                "board:test": {"ok": False, "errors": 1}
            })
        state.export_health(db, health_path, stats={"outcome": "partial"})
    health = json.loads(health_path.read_text(encoding="utf-8"))
    assert len(health["runs"]) == 30
    assert health["last_successful_run_at"] == success
    assert health["sources"]["board:test"]["last_successful_at"] == success


def test_failed_health_replace_preserves_previous_valid_export(tmp_path, monkeypatch):
    path = tmp_path / "db"
    init(path)
    health = tmp_path / "health.json"
    original = '{"llm_usage": []}'
    health.write_text(original, encoding="utf-8")
    def fail_replace(*args):
        raise OSError("locked")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with Database(path) as db, pytest.raises(OSError, match="locked"):
        state.export_health(db, health, stats={"outcome": "ok"})
    assert health.read_text(encoding="utf-8") == original


def test_malformed_saved_health_is_not_overwritten_after_failed_restore(
    isolated_run, monkeypatch,
):
    path = Path(isolated_run.health_json)
    original = "{invalid saved quota state"
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(pipeline, "gather", lambda *args, **kwargs: pytest.fail("must not ingest"))
    with pytest.raises(ValueError, match="invalid health state"):
        pipeline.run(isolated_run, sync_telegram=False)
    assert path.read_text(encoding="utf-8") == original
