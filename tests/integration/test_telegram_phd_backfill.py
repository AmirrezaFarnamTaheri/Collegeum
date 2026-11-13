"""Historical Economics PhDs must be delivered once without rewriting web/X state."""
from unittest.mock import Mock

from predoc_pipeline import pipeline
from predoc_pipeline.boards.config import Preferences
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.models import Discipline, Location, PredocListing
from predoc_pipeline.publish.telegram import render_keyboard
from predoc_pipeline.routing import Router
from predoc_pipeline.settings import Settings


def _phd():
    return PredocListing(
        title="PhD Researcher in Applied Economics",
        institution="Example University",
        location=Location(country="Germany", city="Berlin"),
        disciplines=[Discipline.APPLIED_MICRO],
        summary="Doctoral researcher studying labor economics",
        apply_url="https://example.org/ad/1",
        source_url="https://example.org/ad/1",
    )


def test_save_button_deep_link_encodes_stable_listing_key():
    keyboard = render_keyboard(_phd(), url_hash="a"*64,
                               bot_username="collegeum_example_bot")
    links = [button for row in keyboard["inline_keyboard"] for button in row
             if button.get("text", "").startswith("🔖")]
    assert len(links) == 1
    assert links[0]["url"] == "https://t.me/collegeum_example_bot?start=f_" + "a"*16


def test_phd_backfill_once_and_preserves_existing_web_receipts(tmp_path):
    path = tmp_path / "jobs.db"
    init(path)
    config = Settings(_env_file=None, telegram_bot_token="offline-token",
                      telegram_public_channel_id="@example",
                      telegram_bot_username="collegeum_example_bot",
                      telegram_non_us_econ_phd_enabled=True)
    with Database(path) as db:
        listing = _phd()
        row = pipeline._listing_row(listing, source="test", signature=None)
        lid = db.insert_listing(row)
        db.mark_published(lid, None, x_post_id="prior-tweet")
        published_at = db.listing(lid)["published_at"]
        telegram = Mock()
        telegram.send_message.return_value = 789
        stats = pipeline.RunStats()
        router = Router(Preferences())
        pipeline._publish_non_us_econ_phds(
            db, telegram, config, stats, router, Preferences(), fresh_ids=set(),
            verify=False,
        )
        assert telegram.send_message.call_count == 1
        sent = db.listing(lid)
        assert sent["telegram_message_id"] == 789
        assert sent["published_at"] == published_at
        assert sent["x_post_id"] == "prior-tweet"
        assert db.telegram_state(lid) == "confirmed"
        assert "Previously collected" in telegram.send_message.call_args.kwargs["html"]
        pipeline._publish_non_us_econ_phds(
            db, telegram, config, stats, router, Preferences(), fresh_ids=set(),
            verify=False,
        )
        assert telegram.send_message.call_count == 1


def test_non_us_phd_channel_feature_disabled_by_default(tmp_path):
    path = tmp_path / "jobs.db"
    init(path)
    with Database(path) as db:
        listing = _phd()
        lid = db.insert_listing(pipeline._listing_row(listing, source="test", signature=None))
        db.mark_published(lid, None)
        tg = Mock()
        pipeline._publish_non_us_econ_phds(
            db, tg, Settings(_env_file=None), pipeline.RunStats(),
            Router(Preferences()), Preferences(), fresh_ids=set(), verify=False,
        )
        tg.send_message.assert_not_called()
