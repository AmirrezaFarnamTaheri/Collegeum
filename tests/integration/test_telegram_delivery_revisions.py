"""Verified retry decisions survive stale journals without erasing newer holds."""

from __future__ import annotations

import pytest

from predoc_pipeline import pipeline, state
from predoc_pipeline.core.db import SCHEMA_VERSION, Database, init


@pytest.fixture
def databases(tmp_path):
    paths = [tmp_path / name for name in ("current.db", "cached.db")]
    for path in paths:
        init(path)
    with Database(paths[0]) as current, Database(paths[1]) as cached:
        yield current, cached


def _seed(db, key="job", *, source_url=None):
    return db.insert_listing({
        "url_hash": key, "apply_url": f"https://example.org/{key}",
        "source_url": source_url or f"https://example.org/{key}", "source": "test",
        "title": "Research Assistant", "institution": "Example University",
        "country": "United Kingdom",
    })


def test_verified_absence_survives_journal_replay_in_both_directions(databases, tmp_path):
    current, cached = databases
    lid = _seed(current)
    current.mark_status(lid, "delivery-uncertain")
    held_revision = current.listing(lid)["telegram_delivery_revision"]
    held_path = tmp_path / "held.ndjson"
    resolved_path = tmp_path / "resolved.ndjson"
    state.write_journal(current, held_path)
    state.restore_if_needed(cached, held_path)

    current.resolve_telegram_delivery(lid, confirmed_not_delivered=True)
    resolved_revision = current.listing(lid)["telegram_delivery_revision"]
    assert resolved_revision > held_revision
    state.write_journal(current, resolved_path)

    state.restore_if_needed(cached, resolved_path)
    state.restore_if_needed(current, held_path)
    for db in databases:
        assert db.listing(lid)["status"] == "pending"
        assert db.listing(lid)["telegram_delivery_revision"] == resolved_revision
        assert [row["id"] for row in db.pending_listings()] == [lid]


def test_new_uncertainty_supersedes_verified_retry_in_both_directions(databases):
    current, cached = databases
    lid = _seed(current)
    current.mark_status(lid, "delivery-uncertain")
    current.resolve_telegram_delivery(lid, confirmed_not_delivered=True)
    resolved_snapshot = current.export_rows()
    cached.import_rows(resolved_snapshot)

    current.mark_status(lid, "delivery-uncertain")
    new_revision = current.listing(lid)["telegram_delivery_revision"]
    assert new_revision > resolved_snapshot[0]["telegram_delivery_revision"]
    cached.import_rows(current.export_rows())
    current.import_rows(resolved_snapshot)

    for db in databases:
        assert db.listing(lid)["status"] == "delivery-uncertain"
        assert db.listing(lid)["telegram_delivery_revision"] == new_revision
        assert not db.pending_listings()


@pytest.mark.parametrize("revision_mode", ["legacy", "older", "equal"])
def test_newer_facts_and_ordinary_pending_cannot_erase_hold(databases, revision_mode):
    current, _ = databases
    lid = _seed(current)
    ordinary_pending = current.export_rows()[0]
    current.mark_status(lid, "delivery-uncertain")
    revision = current.listing(lid)["telegram_delivery_revision"]
    if revision_mode == "legacy":
        ordinary_pending.pop("telegram_delivery_revision")
    elif revision_mode == "equal":
        ordinary_pending["telegram_delivery_revision"] = revision
    ordinary_pending.update(last_seen_at="9999-01-01T00:00:00Z", summary="Corrected facts")

    current.import_rows([ordinary_pending])

    row = current.listing(lid)
    assert row["summary"] == "Corrected facts"
    assert row["status"] == "delivery-uncertain"
    assert row["telegram_delivery_revision"] == revision
    assert not current.pending_listings()


def test_repeated_holds_and_fact_refreshes_do_not_advance_revision(databases):
    current, _ = databases
    lid = _seed(current)
    current.mark_status(lid, "delivery-uncertain")
    revision = current.listing(lid)["telegram_delivery_revision"]
    current.mark_status(lid, "delivery-uncertain")
    current.refresh_listing_facts(lid, {"summary": "Refreshed facts"})
    current.touch_listing(lid)
    assert current.listing(lid)["telegram_delivery_revision"] == revision
    with pytest.raises(ValueError, match="non-fact listing fields"):
        current.refresh_listing_facts(lid, {"telegram_delivery_revision": revision + 1})


@pytest.mark.parametrize("terminal_status", ["published", "rejected"])
def test_receipts_and_rejection_win_over_newer_retry_revision(databases, terminal_status):
    current, cached = databases
    lid = _seed(current)
    cached.import_rows(current.export_rows())
    cached.mark_published(lid, 777, x_post_id="x-receipt")
    cached.mark_status(lid, terminal_status)
    acknowledged = cached.export_rows()
    current.mark_status(lid, "delivery-uncertain")
    current.resolve_telegram_delivery(lid, confirmed_not_delivered=True)
    resolved_revision = current.listing(lid)["telegram_delivery_revision"]

    cached.import_rows(current.export_rows())
    current.import_rows(acknowledged)

    for db in databases:
        row = db.listing(lid)
        assert row["status"] == terminal_status
        assert row["telegram_message_id"] == 777
        assert row["x_post_id"] == "x-receipt"
        assert row["telegram_delivery_revision"] == resolved_revision
        assert not db.pending_listings()


def test_delivery_revision_does_not_hide_conflicting_receipts(databases):
    current, cached = databases
    lid = _seed(current)
    cached.import_rows(current.export_rows())
    current.mark_published(lid, 777)
    cached.mark_status(lid, "delivery-uncertain")
    cached.resolve_telegram_delivery(lid, message_id=888)

    with pytest.raises(ValueError, match="conflicting telegram_message_id"):
        current.import_rows(cached.export_rows())
    assert current.listing(lid)["telegram_message_id"] == 777


@pytest.mark.parametrize("alias_status", ["pending", "unpublished"])
def test_resolution_covers_alias_held_only_in_old_cache(databases, alias_status):
    current, cached = databases
    source_url = "https://example.org/adverts/research"
    lid = _seed(current, "first", source_url=source_url)
    alias = _seed(current, "alias", source_url=f"{source_url}?utm_source=feed")
    current.mark_status(lid, "delivery-uncertain")
    current.mark_status(alias, alias_status)
    cached.import_rows(current.export_rows())
    candidates = [(alias, pipeline._listing_from_row(cached.listing(alias)))]
    assert pipeline._group_broadcast_candidates(candidates, cached)[0] == []
    assert cached.listing(alias)["status"] == "delivery-uncertain"
    stale_hold = cached.export_rows()

    current.resolve_telegram_delivery(lid, confirmed_not_delivered=True)
    resolved_revision = current.listing(lid)["telegram_delivery_revision"]
    assert current.listing(alias)["status"] == alias_status
    assert current.listing(alias)["telegram_delivery_revision"] == resolved_revision
    cached.import_rows(current.export_rows())
    current.import_rows(stale_hold)

    for db in databases:
        assert db.listing(lid)["status"] == "pending"
        assert db.listing(alias)["status"] == alias_status
        assert len(db.pending_listings()) == 2


def test_inherited_hold_does_not_manufacture_newer_alias_revision(databases):
    current, cached = databases
    source_url = "https://example.org/adverts/research"
    alias = _seed(current, "alias", source_url=source_url)
    current.mark_status(alias, "delivery-uncertain")
    current.resolve_telegram_delivery(alias, confirmed_not_delivered=True)
    prior_revision = current.listing(alias)["telegram_delivery_revision"]
    # A newly discovered alias can fail after a prior alias was reconciled.
    lid = _seed(current, "new", source_url=source_url)
    current.mark_status(lid, "delivery-uncertain")
    cached.import_rows(current.export_rows())
    candidates = [(alias, pipeline._listing_from_row(cached.listing(alias)))]
    assert pipeline._group_broadcast_candidates(candidates, cached)[0] == []
    assert cached.listing(alias)["status"] == "delivery-uncertain"
    assert cached.listing(alias)["telegram_delivery_revision"] == prior_revision
    stale_hold = cached.export_rows()

    current.resolve_telegram_delivery(lid, confirmed_not_delivered=True)
    cached.import_rows(current.export_rows())
    current.import_rows(stale_hold)
    for db in databases:
        assert {row["id"] for row in db.pending_listings()} == {lid, alias}


@pytest.mark.parametrize("revision", [None, True, False, -1, 1.5, "1", [], {}, 2**63])
def test_invalid_delivery_revision_rolls_back_entire_import(databases, revision):
    current, cached = databases
    _seed(current)
    valid = current.export_rows()[0]
    invalid = {**valid, "id": 2, "url_hash": "invalid", "telegram_delivery_revision": revision}

    with pytest.raises(ValueError, match="delivery revision"):
        cached.import_rows([valid, invalid])
    assert cached.export_rows() == []


def test_old_cached_database_migrates_without_inventing_delivery_evidence(tmp_path):
    path = tmp_path / "legacy.db"
    init(path)
    with Database(path) as db:
        lid = _seed(db)
        db.mark_status(lid, "delivery-uncertain")
        legacy_record = db.export_rows()[0]
        legacy_record.pop("telegram_delivery_revision")
        # Simulate an existing v8 cache: this column did not exist there.
        db.conn.execute("ALTER TABLE listings DROP COLUMN telegram_delivery_revision")
        db.set_meta("schema_version", "8")

    init(path)
    with Database(path) as db:
        assert db.get_meta("schema_version") == str(SCHEMA_VERSION)
        assert db.listing(lid)["telegram_delivery_revision"] == 0
        db.import_rows([{**legacy_record, "status": "pending"}])
        assert db.listing(lid)["status"] == "delivery-uncertain"
        db.resolve_telegram_delivery(lid, confirmed_not_delivered=True)
        assert db.listing(lid)["telegram_delivery_revision"] > 0
        assert [row["id"] for row in db.pending_listings()] == [lid]

    init(path)
    with Database(path) as db:
        assert db.listing(lid)["telegram_delivery_revision"] > 0
        assert db.listing(lid)["status"] == "pending"
