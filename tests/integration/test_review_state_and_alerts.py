"""Salary correction replay, partial refreshes and final alert outcomes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from predoc_pipeline import pipeline, state
from predoc_pipeline.boards.config import Preferences
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.urls import url_hash
from predoc_pipeline.models import salary_value_is_artifact
from predoc_pipeline.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def _record(**changes):
    url = "https://example.org/jobs/research-assistant"
    record = {
        "id": 1, "url_hash": url_hash(url), "apply_url": url, "source_url": url,
        "source": "test", "title": "Research Assistant in Economics",
        "institution": "Example University", "country": "United Kingdom",
        "summary": "Economics research and statistical analysis.",
        "disciplines": ["economics"], "visa_sponsorship_status": "unknown",
        "first_seen_at": "2026-10-11T00:00:00Z",
        "last_seen_at": "2026-10-11T00:00:00Z", "status": "pending",
    }
    record.update(changes)
    return record


def test_committed_salary_correction_survives_existing_cache_and_reexport(tmp_path):
    journal = ROOT / "data" / "listings.ndjson"
    if not journal.exists():
        pytest.skip("production journal is not included in source distributions")
    corrected = next(row for row in state.read_journal(journal) if row["id"] == 148)
    stale = {
        **corrected,
        "salary_min": 2026.0,
        "salary_max": 2026.0,
    }
    replay = tmp_path / "listings.ndjson"
    replay.write_text(json.dumps(corrected) + "\n", encoding="utf-8")
    db_path = tmp_path / "cache.db"
    init(db_path)
    with Database(db_path) as db:
        db.import_rows([stale])
        assert state.restore_if_needed(db, replay) == 0
        restored = db.listing(148)
        assert restored["salary_min"] is None
        assert restored["salary_max"] is None
        assert restored["salary_raw"] == corrected["salary_raw"]
        assert restored["closed_at"] == corrected["closed_at"]
        assert restored["status"] == corrected["status"]
        state.write_journal(db, replay)
    exported = state.read_journal(replay)[0]
    assert exported["salary_min"] is None
    assert exported["salary_max"] is None
    assert exported["last_seen_at"] >= corrected["last_seen_at"]


@pytest.mark.parametrize("case", ["newer_cache", "valid_salary", "changed_raw", "missing_null"])
def test_journal_salary_repair_preserves_unproven_or_newer_local_facts(tmp_path, case):
    incoming = _record(salary_min=None, salary_max=None, salary_raw="2026 rates")
    cached = {**incoming, "salary_min": 2026.0}
    if case == "newer_cache":
        cached["last_seen_at"] = "2026-10-12T00:00:00Z"
    elif case == "valid_salary":
        incoming["salary_raw"] = cached["salary_raw"] = "£2026 stipend"
    elif case == "changed_raw":
        cached["salary_raw"] = "£2026 stipend"
    else:
        del incoming["salary_min"]
    journal = tmp_path / "listings.ndjson"
    journal.write_text(json.dumps(incoming) + "\n", encoding="utf-8")
    db_path = tmp_path / "cache.db"
    init(db_path)
    with Database(db_path) as db:
        db.import_rows([cached])
        state.restore_if_needed(db, journal)
        row = db.listing(1)
        assert row["salary_min"] == 2026.0
        assert row["salary_raw"] == cached["salary_raw"]
        assert row["last_seen_at"] == cached["last_seen_at"]


_VALID_YEAR_SHAPED_SALARIES = [
    ("£2000 stipend", 2000.0),
    ("monthly salary EUR 2026", 2026.0),
    ("USD 2000–2100", 2100.0),
    ("£2000 or €2300 depending on location", 2000.0),
    ("2000 EUR per month or GBP 1800 per month", 2000.0),
    ("£1000 bonus plus £2000 stipend", 2000.0),
    ("£1800 minimum, £2000 midpoint, £2200 maximum", 2000.0),
    ("2000–2300 EUR or GBP 1800–2100", 2000.0),
    ("2000 monthly", 2000.0),
    ("monthly stipend: 2000", 2000.0),
    ("2026 rates include a £2026 stipend or €2300", 2026.0),
]


@pytest.mark.parametrize("raw, amount", _VALID_YEAR_SHAPED_SALARIES)
def test_salary_artifact_guard_keeps_each_currency_or_pay_qualified_amount(raw, amount):
    assert not salary_value_is_artifact(amount, raw)


@pytest.mark.parametrize("raw, amount", _VALID_YEAR_SHAPED_SALARIES)
def test_equal_timestamp_journal_null_does_not_erase_real_pay(tmp_path, raw, amount):
    cached = _record(salary_min=amount, salary_max=amount, salary_raw=raw)
    incoming = {**cached, "salary_min": None, "salary_max": None}
    journal = tmp_path / "listings.ndjson"
    journal.write_text(json.dumps(incoming) + "\n", encoding="utf-8")
    db_path = tmp_path / "cache.db"
    init(db_path)
    with Database(db_path) as db:
        db.import_rows([cached])
        state.restore_if_needed(db, journal)
        restored = db.listing(1)
        assert restored["salary_min"] == amount
        assert restored["salary_max"] == amount
        assert restored["last_seen_at"] == cached["last_seen_at"]


@pytest.mark.parametrize("raw, amount", _VALID_YEAR_SHAPED_SALARIES)
def test_incomplete_salary_refresh_preserves_currency_qualified_amount(tmp_path, raw, amount):
    db_path = tmp_path / "cache.db"
    init(db_path)
    with Database(db_path) as db:
        db.import_rows([_record(salary_min=amount, salary_max=amount, salary_raw=raw)])
        stored = db.listing(1)
        partial = pipeline._listing_from_row(stored).model_copy(update={
            "salary_min": None, "salary_max": None, "salary_raw": None,
        })
        pipeline._clear_stale_salary(db, 1, stored, partial, {})
        assert db.listing(1)["salary_min"] == amount
        assert db.listing(1)["salary_max"] == amount


def test_clearing_one_bad_bound_preserves_metadata_for_surviving_salary(tmp_path):
    db_path = tmp_path / "cache.db"
    init(db_path)
    with Database(db_path) as db:
        db.import_rows([_record(
            salary_min=2026.0, salary_max=50_000.0, salary_currency="GBP",
            salary_period="year", salary_raw="2026 rates; salary up to £50,000 per annum",
        )])
        stored = db.listing(1)
        partial = pipeline._listing_from_row(stored).model_copy(update={
            "salary_min": None, "salary_max": None, "salary_currency": None,
            "salary_period": None, "salary_raw": None,
        })
        pipeline._clear_stale_salary(db, 1, stored, partial, {})
        corrected = db.listing(1)
        assert corrected["salary_min"] is None
        assert corrected["salary_max"] == 50_000.0
        assert corrected["salary_currency"] == "GBP"
        assert corrected["salary_period"] == "year"


def test_undelivered_alert_is_included_in_final_run_outcome(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None, db_path=str(tmp_path / "cache.db"),
        state_path=str(tmp_path / "listings.ndjson"),
        seen_state_path=str(tmp_path / "seen.ndjson"),
        dashboard_json=str(tmp_path / "listings.json"),
        health_json=str(tmp_path / "health.json"), feed_path=str(tmp_path / "feed.xml"),
        dlq_path=str(tmp_path / "dlq.json"), feedback_path=str(tmp_path / "feedback.json"),
        feedback_encryption_key="", telegram_state_path=str(tmp_path / "telegram.json"),
        career_state_path=str(tmp_path / "career.ndjson"),
        career_health_path=str(tmp_path / "career-health.json"),
        life_sciences_rotation_path=str(tmp_path / "life-rotation.json"),
        enable_career_feeds=False,
        extraction_backend="heuristic", telegram_bot_token="", x_broadcast_enabled=False,
        source_rotation_enabled=False, empty_run_alert_threshold=1,
        telegram_operational_alerts_enabled=True,
    )
    prefs = Preferences()
    prefs.enrich.fetch_details = False
    monkeypatch.setattr(pipeline, "load_preferences", lambda _: prefs)
    monkeypatch.setattr(pipeline, "load_sources", lambda _: [])
    monkeypatch.setattr(pipeline, "gather", lambda *_args, **_kwargs: ([], {}))
    monkeypatch.setattr("predoc_pipeline.alerts.notify_admin", lambda *_args: False)

    stats = pipeline.run(settings, sync_telegram=False)

    assert stats.errors == 1
    assert stats.outcome == "partial"
    with Database(settings.db_path) as db:
        last_run = db.recent_runs()[0]
        assert last_run["errors"] == 1
        assert last_run["outcome"] == "partial"
    health = json.loads(Path(settings.health_json).read_text(encoding="utf-8"))
    assert health["last_run"]["outcome"] == "partial"
    assert health["status"] == "degraded"


def test_pending_count_matches_retryable_queue_including_unpublished_rows(tmp_path):
    db_path = tmp_path / "cache.db"
    init(db_path)
    cases = [
        {"status": "pending", "deadline": "2099-01-01T00:00:00Z"},
        {"status": "unpublished", "deadline": None},
        {"status": "pending", "deadline": "2000-01-01T00:00:00Z"},
        {"status": "unpublished", "closed_at": "2026-10-01T00:00:00Z"},
        {"status": "pending", "expired_at": "2026-10-01T00:00:00Z"},
        {"status": "delivery-uncertain"},
        {"status": "published"},
    ]
    with Database(db_path) as db:
        for i, case in enumerate(cases, 1):
            db.import_rows([
                _record(id=i, url_hash=url_hash(f"https://example.org/jobs/{i}"), **case),
            ])
            assert db.counts()["pending"] == len(db.pending_listings())
        assert [row["id"] for row in db.pending_listings()] == [1, 2]
        assert db.counts()["pending"] == 2
        assert db.counts()["pending_closed"] == 3
