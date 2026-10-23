"""Duplicate aliases share confirmed delivery outcomes, never assumed sends."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from predoc_pipeline import pipeline, state
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.models import Location, PredocListing
from predoc_pipeline.publish.telegram import TelegramError
from predoc_pipeline.settings import Settings


def _candidates(db, groups=2):
    candidates = []
    for group in range(groups):
        for variant in ("first", "alias"):
            listing = PredocListing(
                title=f"Research Assistant {group}", institution="Example University",
                location=Location(country="United Kingdom"),
                apply_url=f"https://example.org/jobs/{group}/{variant}",
                source_url=f"https://example.org/adverts/{group}",
            )
            row = pipeline._listing_row(listing, source="test", signature=None)
            candidates.append((db.insert_listing(row), listing))
    return candidates


@pytest.mark.parametrize("digest", [False, True])
@pytest.mark.parametrize("outcome", ["success", "failed", "uncertain"])
def test_same_run_aliases_follow_actual_send_and_recovery(tmp_path, digest, outcome):
    db_path = tmp_path / "cache.db"
    init(db_path)
    settings = Settings(
        _env_file=None, telegram_bot_token="offline-token",
        telegram_public_channel_id="123", telegram_digest_threshold=1 if digest else 0,
    )
    telegram = Mock()
    if outcome == "success":
        telegram.send_message.return_value = 777
    else:
        telegram.send_message.side_effect = TelegramError(
            "no acknowledgement" if outcome == "uncertain" else "gateway unavailable",
            status=None if outcome == "uncertain" else 503,
            uncertain=outcome == "uncertain",
        )
    with Database(db_path) as db:
        candidates = _candidates(db)
        stats = pipeline.RunStats()
        pipeline._broadcast(candidates, telegram, settings, db, stats)

        assert telegram.send_message.call_count == (1 if digest else 2)
        expected = {
            "success": "published", "failed": "pending", "uncertain": "delivery-uncertain",
        }[outcome]
        for listing_id, _ in candidates:
            row = db.listing(listing_id)
            assert row["status"] == expected
            assert row["telegram_message_id"] == (777 if outcome == "success" else None)
            assert bool(row["published_at"]) is (outcome == "success")
        assert stats.published == (2 if outcome == "success" else 0)
        state.write_journal(db, tmp_path / "listings.ndjson")

    recovered_path = tmp_path / "recovered.db"
    init(recovered_path)
    with Database(recovered_path) as recovered:
        state.restore_if_needed(recovered, tmp_path / "listings.ndjson")
        assert len(recovered.pending_listings()) == (4 if outcome == "failed" else 0)


def test_alias_of_already_delivered_listing_preserves_remote_receipt(tmp_path):
    db_path = tmp_path / "cache.db"
    init(db_path)
    with Database(db_path) as db:
        candidates = _candidates(db, groups=1)
        first_id, _ = candidates[0]
        alias_id, _ = candidates[1]
        db.mark_published(first_id, 701)
        telegram = Mock()
        pipeline._broadcast(
            [candidates[1]], telegram, Settings(_env_file=None), db, pipeline.RunStats(),
        )
        telegram.send_message.assert_not_called()
        assert db.listing(alias_id)["telegram_message_id"] == 701
        assert db.listing(alias_id)["published_at"]


def _bridge_candidates(db):
    candidates = []
    # The fourth row connects two representatives and the second one's alias.
    for apply, source in (("a", "b"), ("c", "d"), ("e", "d"), ("b", "d")):
        listing = PredocListing(
            title="Research Assistant", institution="Example University",
            location=Location(country="United Kingdom"),
            apply_url=f"https://example.org/{apply}",
            source_url=f"https://example.org/{source}",
        )
        row = pipeline._listing_row(listing, source="test", signature=None)
        candidates.append((db.insert_listing(row), listing))
    return candidates


@pytest.mark.parametrize("outcome", ["success", "failed", "uncertain"])
def test_bridge_merges_previously_distinct_candidate_groups(tmp_path, outcome):
    db_path = tmp_path / "cache.db"
    init(db_path)
    telegram = Mock()
    if outcome == "success":
        telegram.send_message.return_value = 777
    else:
        telegram.send_message.side_effect = TelegramError(
            "missing acknowledgement" if outcome == "uncertain" else "unavailable",
            status=None if outcome == "uncertain" else 503,
            uncertain=outcome == "uncertain",
        )
    with Database(db_path) as db:
        candidates = _bridge_candidates(db)
        pipeline._broadcast(
            candidates, telegram, Settings(_env_file=None), db, pipeline.RunStats(),
        )
        telegram.send_message.assert_called_once()
        expected = {
            "success": "published", "failed": "pending", "uncertain": "delivery-uncertain",
        }[outcome]
        for lid, _ in candidates:
            row = db.listing(lid)
            assert row["status"] == expected
            assert row["telegram_message_id"] == (777 if outcome == "success" else None)
        assert len(db.pending_listings()) == (4 if outcome == "failed" else 0)


def test_bridge_to_confirmed_receipt_suppresses_entire_candidate_group(tmp_path):
    db_path = tmp_path / "cache.db"
    init(db_path)
    telegram = Mock()
    with Database(db_path) as db:
        candidates = _bridge_candidates(db)
        db.mark_published(candidates[0][0], 701)
        pipeline._broadcast(
            candidates[1:], telegram, Settings(_env_file=None), db, pipeline.RunStats(),
        )
        telegram.send_message.assert_not_called()
        for lid, _ in candidates:
            assert db.listing(lid)["status"] == "published"
            assert db.listing(lid)["telegram_message_id"] == 701


def test_recovered_pending_alias_inherits_prior_uncertain_hold(tmp_path):
    db_path = tmp_path / "cache.db"
    init(db_path)
    settings = Settings(_env_file=None)
    with Database(db_path) as db:
        candidates = _candidates(db, groups=1)
        uncertain = Mock()
        uncertain.send_message.side_effect = TelegramError(
            "missing acknowledgement", uncertain=True,
        )
        # The alias was already stored but excluded from the first run's sends.
        pipeline._broadcast(candidates[:1], uncertain, settings, db, pipeline.RunStats())
        assert db.listing(candidates[1][0])["status"] == "pending"
        state.write_journal(db, tmp_path / "listings.ndjson")

    recovered_path = tmp_path / "recovered.db"
    init(recovered_path)
    with Database(recovered_path) as db:
        state.restore_if_needed(db, tmp_path / "listings.ndjson")
        telegram = Mock()
        pending = [(row["id"], pipeline._listing_from_row(row)) for row in db.pending_listings()]
        pipeline._broadcast(pending, telegram, settings, db, pipeline.RunStats())
        telegram.send_message.assert_not_called()
        assert not db.pending_listings()
        for lid, _ in candidates:
            assert db.listing(lid)["status"] == "delivery-uncertain"
            assert db.listing(lid)["telegram_message_id"] is None

        # One operator-confirmed absence releases the held submission's aliases
        # together; a leftover alias must not undo that explicit resolution.
        db.resolve_telegram_delivery(candidates[0][0], confirmed_not_delivered=True)
        pending = [(row["id"], pipeline._listing_from_row(row)) for row in db.pending_listings()]
        telegram.send_message.return_value = 777
        pipeline._broadcast(pending, telegram, settings, db, pipeline.RunStats())
        telegram.send_message.assert_called_once()
        for lid, _ in candidates:
            assert db.listing(lid)["status"] == "published"
            assert db.listing(lid)["telegram_message_id"] == 777


def test_prior_uncertain_hold_propagates_through_current_bridge_group(tmp_path):
    db_path = tmp_path / "cache.db"
    init(db_path)
    with Database(db_path) as db:
        candidates = _bridge_candidates(db)
        db.mark_status(candidates[0][0], "delivery-uncertain")
        telegram = Mock()
        pipeline._broadcast(
            candidates[1:], telegram, Settings(_env_file=None), db, pipeline.RunStats(),
        )
        telegram.send_message.assert_not_called()
        assert not db.pending_listings()
        assert all(db.listing(lid)["status"] == "delivery-uncertain" for lid, _ in candidates)


def test_confirmed_receipt_takes_precedence_over_prior_alias_hold(tmp_path):
    db_path = tmp_path / "cache.db"
    init(db_path)
    with Database(db_path) as db:
        candidates = _bridge_candidates(db)
        db.mark_status(candidates[0][0], "delivery-uncertain")
        db.mark_published(candidates[1][0], 701)
        telegram = Mock()
        pipeline._broadcast(
            candidates[2:], telegram, Settings(_env_file=None), db, pipeline.RunStats(),
        )
        telegram.send_message.assert_not_called()
        for lid, _ in candidates[1:]:
            assert db.listing(lid)["status"] == "published"
            assert db.listing(lid)["telegram_message_id"] == 701


@pytest.mark.parametrize("prior_status", ["delivery-uncertain", "published"])
def test_stored_bridge_outside_current_candidates_propagates_delivery_evidence(
    tmp_path, prior_status,
):
    db_path = tmp_path / "cache.db"
    init(db_path)
    with Database(db_path) as db:
        candidates = _bridge_candidates(db)
        first_id, _ = candidates[0]
        if prior_status == "published":
            db.mark_published(first_id, 701)
        else:
            db.mark_status(first_id, prior_status)
        telegram = Mock()
        # A=(a,b) supplies evidence, B=(c,d) is eligible, C=(b,d) is a
        # stored bridge excluded by today's policy/verification stage.
        pipeline._broadcast(
            [candidates[1]], telegram, Settings(_env_file=None), db, pipeline.RunStats(),
        )
        telegram.send_message.assert_not_called()
        eligible = db.listing(candidates[1][0])
        assert eligible["status"] == prior_status
        assert eligible["telegram_message_id"] == (701 if prior_status == "published" else None)
        assert db.listing(first_id)["status"] == prior_status
        for lid, _ in candidates[2:]:
            assert db.listing(lid)["status"] == "pending"
            assert db.listing(lid)["telegram_message_id"] is None


@pytest.mark.parametrize("message_id", [None, 701])
def test_manual_reconciliation_traverses_pending_bridges_and_changes_only_holds(
    tmp_path, message_id,
):
    db_path = tmp_path / "cache.db"
    init(db_path)
    with Database(db_path) as db:
        candidates = _bridge_candidates(db)
        for lid, _ in candidates[:2]:
            db.mark_status(lid, "delivery-uncertain")
        db.mark_published(candidates[2][0], 900)
        unrelated = _candidates(db, groups=1)[0][0]
        db.mark_status(unrelated, "delivery-uncertain")

        db.resolve_telegram_delivery(
            candidates[0][0], message_id=message_id,
            confirmed_not_delivered=message_id is None,
        )

        for lid, _ in candidates[:2]:
            assert db.listing(lid)["status"] == ("published" if message_id else "pending")
            assert db.listing(lid)["telegram_message_id"] == message_id
        assert db.listing(candidates[2][0])["telegram_message_id"] == 900
        assert db.listing(candidates[2][0])["status"] == "published"
        assert db.listing(candidates[3][0])["status"] == "pending"
        assert db.listing(unrelated)["status"] == "delivery-uncertain"
