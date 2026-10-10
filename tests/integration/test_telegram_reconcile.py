"""Ambiguous Telegram delivery cannot be retried without explicit reconciliation."""

import pytest

from predoc_pipeline.core.db import Database, init
from predoc_pipeline.publish.feedback import FeedbackStore


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "listings.db"
    init(path)
    with Database(path) as database:
        yield database


def _make(db, key="example"):
    return db.insert_listing({
        "url_hash": key, "apply_url": f"https://example.org/{key}",
        "source_url": f"https://example.org/{key}", "source": "test",
        "title": "Research assistant", "institution": "Example University",
    })


def test_reconcile_unknown_outcome_requires_verification(db):
    lid = _make(db)
    db.mark_status(lid, "delivery-uncertain")
    with pytest.raises(ValueError):
        db.resolve_telegram_delivery(lid)
    with pytest.raises(ValueError):
        db.resolve_telegram_delivery(lid, message_id=1,
                                     confirmed_not_delivered=True)
    assert db.listing(lid)["status"] == "delivery-uncertain"


def test_verified_delivery_is_idempotent(db):
    lid = _make(db)
    db.mark_status(lid, "delivery-uncertain")
    db.resolve_telegram_delivery(lid, message_id=12345)
    db.resolve_telegram_delivery(lid, message_id=12345)
    row = db.listing(lid)
    assert row["status"] == "published"
    assert row["telegram_message_id"] == 12345
    with pytest.raises(ValueError):
        db.resolve_telegram_delivery(lid, confirmed_not_delivered=True)


def test_confirmed_absence_requeues_only_uncertain_listing(db):
    lid = _make(db)
    db.mark_status(lid, "delivery-uncertain")
    assert not db.pending_listings()
    db.resolve_telegram_delivery(lid, confirmed_not_delivered=True)
    assert [r["id"] for r in db.pending_listings()] == [lid]


def test_callback_replays_survive_more_than_500_subsequent_updates(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.json")
    store.remember_callback("very-old")
    for number in range(550):
        store.remember_callback(f"new-{number}")
    store.save()
    restored = FeedbackStore(tmp_path / "feedback.json")
    assert restored.callback_seen("very-old")
    assert restored.callback_seen("new-549")
