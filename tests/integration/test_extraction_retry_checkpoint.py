"""Model extraction failures have bounded, durable, content-scoped retries."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from predoc_pipeline import pipeline
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.models import RawItem


def test_retry_waits_backs_off_and_stops_after_three_identical_failures(tmp_path, monkeypatch):
    path = tmp_path / "retry.db"
    init(path)
    instant = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    marker = "candidate-v4:no-policy:evidence-one"
    item = RawItem(source="rss", source_url="https://example.org/predoc", text="Economics",
                   title="Research Assistant in Economics")
    monkeypatch.setattr(pipeline, "utcnow", lambda: instant)
    with Database(path) as db:
        source_key = "a" * 64
        assert not pipeline._extraction_retry_due(None, marker, now=instant)
        pipeline._record_extraction_failure(db, item, source_key, marker)
        seen = db.seen(source_key)
        assert seen["decision"] == "extract_error"
        assert seen["reason"].startswith("extract-retry-v1|1|")
        assert not pipeline._extraction_retry_due(seen, marker, now=instant)
        assert pipeline._extraction_retry_due(seen, marker, now=instant + timedelta(hours=9))
        monkeypatch.setattr(pipeline, "utcnow", lambda: instant + timedelta(hours=9))
        pipeline._record_extraction_failure(db, item, source_key, marker)
        seen = db.seen(source_key)
        assert seen["reason"].startswith("extract-retry-v1|2|")
        assert not pipeline._extraction_retry_due(seen, marker, now=instant + timedelta(hours=9))
        assert pipeline._extraction_retry_due(seen, marker, now=instant + timedelta(hours=26))
        monkeypatch.setattr(pipeline, "utcnow", lambda: instant + timedelta(hours=26))
        pipeline._record_extraction_failure(db, item, source_key, marker)
        seen = db.seen(source_key)
        assert seen["reason"].startswith("extract-retry-v1|3|")
        assert not pipeline._extraction_retry_due(seen, marker, now=instant + timedelta(days=60))
        assert pipeline._extraction_retry_due(
            seen, "candidate-v4:no-policy:new-evidence", now=instant
        )


def test_extraction_retry_checkpoint_roundtrips_through_committed_seen(tmp_path, monkeypatch):
    from predoc_pipeline import state

    first = tmp_path / "one.db"
    second = tmp_path / "two.db"
    init(first)
    init(second)
    instant = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(pipeline, "utcnow", lambda: instant)
    item = RawItem(source="board", source_url="https://example.org/opening",
                   text="Research", title="Research Assistant")
    source_key = "b" * 64
    digest = "candidate-v4:policy:one"
    path = tmp_path / "seen.ndjson"
    with Database(first) as db:
        pipeline._record_extraction_failure(db, item, source_key, digest)
        state.write_seen(db, path)
    with Database(second) as restored:
        restored.import_seen(state.read_journal(path))
        checkpoint = restored.seen(source_key)
        assert checkpoint["reason"].startswith("extract-retry-v1|1|")
        assert not pipeline._extraction_retry_due(checkpoint, digest, now=instant)
        assert pipeline._extraction_retry_due(
            checkpoint, digest, now=instant + timedelta(days=2)
        )

def test_duplicate_failure_does_not_consume_second_attempt(tmp_path, monkeypatch):
    path = tmp_path / "retry-round.db"
    init(path)
    instant = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(pipeline, "utcnow", lambda: instant)
    item = RawItem(source="rss", source_url="https://example.org/predoc",
                   text="Economics", title="Research Assistant in Economics")
    key, digest = "c" * 64, "candidate-v4:policy:unchanged"
    with Database(path) as db:
        pipeline._record_extraction_failure(db, item, key, digest)
        pipeline._record_extraction_failure(db, item, key, digest)
        assert db.seen(key)["reason"].startswith("extract-retry-v1|1|")
