"""Recovery preserves durable identity and fails before losing journal data."""

import json
import sqlite3

import pytest

from predoc_pipeline import state
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.dedupe import Deduplicator
from predoc_pipeline.pipeline import run
from predoc_pipeline.settings import Settings


def record(key="one", **extra):
    return {
        "url_hash": key, "title": "Research Fellow in Applied Economics",
        "institution": "Example University", "source_url": f"https://example.org/{key}",
        "apply_url": f"https://example.org/{key}",
        "first_seen_at": "2026-10-05T00:00:00Z", "last_seen_at": "2026-10-05T00:00:00Z",
        "summary": "Supporting causal inference studies with administrative data "
        "and reproducible statistical analysis in applied microeconomics.",
        **extra,
    }


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "recovery.db"
    init(path)
    with Database(path) as database:
        yield database


def test_restore_preserves_noncontiguous_ids_and_actual_insert_counts(db):
    assert db.import_rows([record("one", id=42), record("two", id=7)]) == 2
    assert db.listing_by_url_hash("one")["id"] == 42
    assert db.listing_by_url_hash("two")["id"] == 7
    assert {row["id"] for row in db.export_rows()} == {7, 42}
    assert db.import_rows([record("one", id=42)]) == 0


@pytest.mark.parametrize("bad", [record("bad", future_unknown_column=1),
                                  record("bad", id=-2), record("bad", id=42)])
def test_restore_batch_rolls_back_invalid_or_conflicting_rows(db, bad):
    with pytest.raises((ValueError, sqlite3.Error)):
        db.import_rows([record("one", id=42), bad])
    assert db.counts()["listings"] == 0


@pytest.mark.parametrize("bad_line", ["{bad json}", "[]", "null", '"text"'])
def test_corrupt_journal_never_restores_partial_state(db, tmp_path, bad_line):
    path = tmp_path / "listings.ndjson"
    original = json.dumps(record()) + "\n" + bad_line + "\n"
    path.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        state.restore_if_needed(db, path)
    assert db.counts()["listings"] == 0
    assert path.read_text(encoding="utf-8") == original


def test_missing_and_empty_journals_remain_valid(db, tmp_path):
    assert state.restore_if_needed(db, tmp_path / "missing") == 0
    assert state.read_journal(tmp_path / "missing") == []


def test_restore_rebuilds_identical_minhash(db):
    data = record()
    db.import_rows([data])
    deduper = Deduplicator()
    deduper.seed(db.conn.execute("SELECT * FROM listings").fetchall())
    match = deduper.find(
        text=f"{data['title']}. {data['summary']}",
        title=data["title"], institution=data["institution"],
    )
    assert match is not None and match.tier == "minhash" and match.score == 1.0


def test_invalid_seen_state_rolls_back_both_journals(db, tmp_path):
    listings = tmp_path / "listings.ndjson"
    seen = tmp_path / "seen.ndjson"
    listings.write_text(json.dumps(record(id=42)), encoding="utf-8")
    seen.write_text(json.dumps({"url_hash": "source", "decision": "accepted",
                               "listing_url_hash": "missing"}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing listing"):
        state.restore_if_needed(db, listings, seen)
    assert db.counts()["listings"] == 0
    assert db.seen_count() == 0


def test_journals_round_trip_stable_ids_and_seen_links(db, tmp_path):
    db.import_rows([record(id=42)])
    db.mark_seen("source-key", source="test", decision="accepted", listing_id=42)
    listings, seen = tmp_path / "listings.ndjson", tmp_path / "seen.ndjson"
    state.write_journal(db, listings)
    state.write_seen(db, seen)
    other = tmp_path / "other.db"
    init(other)
    with Database(other) as restored:
        assert state.restore_if_needed(restored, listings, seen) == 1
        assert restored.listing_by_url_hash("one")["id"] == 42
        assert restored.seen("source-key")["listing_id"] == 42


def test_nested_imports_roll_back_with_outer_transaction(db):
    with pytest.raises(RuntimeError), db.transaction():
        db.import_rows([record(id=42)])
        raise RuntimeError("abort recovery")
    assert db.counts()["listings"] == 0


def test_pipeline_failure_preserves_both_original_journals(tmp_path):
    listings, seen = tmp_path / "listings.ndjson", tmp_path / "seen.ndjson"
    original = json.dumps(record()) + "\n{broken}\n"
    listings.write_text(original, encoding="utf-8")
    seen_original = json.dumps({"url_hash": "source", "decision": "rejected"})
    seen.write_text(seen_original, encoding="utf-8")
    health = tmp_path / "health.json"
    health_original = json.dumps({"llm_usage": [
        {"day": "2026-10-05", "requests": 180, "tokens": 1000, "errors": 2}
    ]})
    health.write_text(health_original, encoding="utf-8")
    settings = Settings(
        _env_file=None, db_path=str(tmp_path / "pipeline.db"),
        state_path=str(listings), seen_state_path=str(seen),
        health_json=str(health), extraction_backend="heuristic",
    )
    with pytest.raises(ValueError, match="line 2"):
        run(settings, sync_telegram=False)
    assert listings.read_text(encoding="utf-8") == original
    assert seen.read_text(encoding="utf-8") == seen_original
    failed_health = json.loads(health.read_text(encoding="utf-8"))
    assert failed_health["llm_usage"] == json.loads(health_original)["llm_usage"]
    assert failed_health["status"] == "fatal"
    with Database(settings.db_path) as restored:
        assert restored.counts()["listings"] == 0
        assert restored.seen_count() == 0


def test_partial_cache_recovers_missing_rows_without_overwriting_newer_values(db, tmp_path):
    db.import_rows([record("one", id=42, summary="Newer cache summary")])
    path = tmp_path / "listings.ndjson"
    path.write_text(
        json.dumps(record("one", id=42)) + "\n" + json.dumps(record("two", id=7)),
        encoding="utf-8",
    )
    assert state.restore_if_needed(db, path) == 1
    assert db.listing_by_url_hash("one")["summary"] == "Newer cache summary"
    assert db.listing_by_url_hash("two")["id"] == 7
    assert state.restore_if_needed(db, path) == 0
