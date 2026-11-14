"""Activation contracts: Economics PhDs go to the existing Predoc channel."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from predoc_pipeline import pipeline
from predoc_pipeline.boards.config import load_preferences
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.models import Discipline, Location, PredocListing
from predoc_pipeline.routing import Router
from predoc_pipeline.settings import Settings


@pytest.mark.parametrize("username", ["", "invalid-username!"])
def test_enabled_phd_backfill_uses_existing_predoc_channel_without_bot_username(
    tmp_path, username,
):
    """Channel publishing must not be blocked by an undeployed favorites UI."""
    path = tmp_path / "jobs.db"
    init(path)
    listing = PredocListing(
        title="PhD Researcher in Applied Economics",
        institution="Example University",
        location=Location(country="Germany", city="Berlin"),
        disciplines=[Discipline.APPLIED_MICRO],
        summary="Doctoral researcher studying labor economics",
        apply_url="https://example.org/doctoral-economics",
        source_url="https://example.org/doctoral-economics",
    )
    settings = Settings(
        _env_file=None,
        telegram_bot_token="offline-test-token",
        telegram_public_channel_id="@existing_predoc_channel",
        telegram_bot_username=username,
        telegram_non_us_econ_phd_enabled=True,
        telegram_non_us_econ_phd_backfill_limit=6,
    )
    prefs = load_preferences(Path(__file__).resolve().parents[2] / "config/preferences.toml")
    with Database(path) as db:
        lid = db.insert_listing(
            pipeline._listing_row(listing, source="test", signature=None)
        )
        db.mark_published(lid, None, x_post_id="existing-post")
        published_at = db.listing(lid)["published_at"]
        telegram = Mock()
        telegram.send_message.return_value = 980
        stats = pipeline.RunStats()
        pipeline._publish_non_us_econ_phds(
            db, telegram, settings, stats, Router(prefs), prefs,
            fresh_ids=set(), verify=False,
        )
        telegram.send_message.assert_called_once()
        sent = telegram.send_message.call_args.kwargs
        assert sent["chat_id"] == "@existing_predoc_channel"
        assert "Previously collected" in sent["html"]
        assert all(
            "Save" not in button["text"]
            for row in (sent["keyboard"] or {}).get("inline_keyboard", [])
            for button in row
        )
        assert db.telegram_state(lid) == "confirmed"
        assert db.listing(lid)["telegram_message_id"] == 980
        assert db.listing(lid)["published_at"] == published_at
        assert db.listing(lid)["x_post_id"] == "existing-post"
        pipeline._publish_non_us_econ_phds(
            db, telegram, settings, stats, Router(prefs), prefs,
            fresh_ids=set(), verify=False,
        )
        telegram.send_message.assert_called_once()


def test_existing_channel_scheduled_rollout_has_bounded_opt_out_default():
    workflow = (
        Path(__file__).resolve().parents[2] / ".github/workflows/pipeline.yml"
    ).read_text()
    assert "vars.TELEGRAM_NON_US_ECON_PHD_ENABLED || 'true'" in workflow
    assert "vars.TELEGRAM_NON_US_ECON_PHD_BACKFILL_LIMIT || '6'" in workflow
