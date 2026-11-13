"""Non-US Economics PhDs receive additive, durable Telegram publication."""
from __future__ import annotations

from predoc_pipeline import state
from predoc_pipeline.boards.config import Preferences
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.models import Discipline, Location, PredocListing
from predoc_pipeline.routing import Channel, Router


def listing(country="Germany", title="PhD Researcher in Applied Economics",
            summary="Doctoral researcher conducting applied economics research.",
            disciplines=None):
    return PredocListing(
        title=title, institution="Example University",
        location=Location(country=country, city="Berlin"),
        disciplines=disciplines if disciplines is not None else [Discipline.APPLIED_MICRO],
        summary=summary, apply_url="https://example.edu/jobs/123",
        source_url="https://example.edu/jobs/123",
    )


def test_additive_non_us_economics_doctoral_routing():
    router = Router(Preferences())
    assert router.destinations(listing()) == frozenset({Channel.WEB, Channel.TELEGRAM})
    assert router.channel_for(listing()) == Channel.WEB  # compatibility for the website
    assert router.destinations(listing(country="United States")) == frozenset({Channel.WEB})
    assert router.destinations(listing(country="")) == frozenset({Channel.WEB})
    assert router.destinations(listing(
        title="PhD in Molecular Genetics", disciplines=[Discipline.OTHER],
        summary="Doctoral student researching genetics.",
    )) == frozenset({Channel.WEB})
    assert router.destinations(listing(
        title="Postdoctoral Researcher in Economics",
        summary="A completed PhD is required.",
    )) == frozenset({Channel.WEB})
    assert router.destinations(listing(
        title="Research Fellow in Economics",
        summary="A completed PhD is required.",
    )) == frozenset({Channel.WEB})
    assert router.destinations(listing(
        title="PhD in Economics - application to graduate degree programme",
        summary="Applications for general admission to the economics PhD programme.",
    )) == frozenset({Channel.WEB})
    assert router.destinations(listing(title="Predoctoral Research Assistant")) == frozenset(
        {Channel.TELEGRAM}
    )


def test_telegram_receipt_survives_journal_and_preserves_web_publication(tmp_path):
    db_file = tmp_path / "source.db"
    restored_file = tmp_path / "restored.db"
    init(db_file)
    init(restored_file)
    with Database(db_file) as db:
        lid = db.insert_listing({
            "url_hash": "b" * 64, "apply_url": "https://example.edu/jobs/123",
            "source_url": "https://example.edu/jobs/123", "source": "test",
            "title": "PhD Researcher in Economics", "institution": "Example University",
            "country": "Germany", "summary": "Doctoral research in economics",
        })
        db.mark_published(lid, None, x_post_id="tweet-1")
        original = db.listing(lid)["published_at"]
        assert db.telegram_state(lid) == "not_attempted"
        db.record_telegram_delivery(lid, "confirmed", message_id=725)
        row = db.listing(lid)
        assert row["published_at"] == original
        assert row["x_post_id"] == "tweet-1"
        assert db.telegram_state(lid) == "confirmed"
        state.write_journal(db, tmp_path / "listings.ndjson")

    with Database(restored_file) as db:
        state.restore_if_needed(db, tmp_path / "listings.ndjson")
        row = db.listing(1)
        assert row["telegram_message_id"] == 725
        assert db.telegram_state(1) == "confirmed"
        assert row["x_post_id"] == "tweet-1"
        assert row["published_at"] == original
