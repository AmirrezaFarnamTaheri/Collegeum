"""Channel announcements must be one listing per message with working Save controls."""
from pathlib import Path
from unittest.mock import Mock

from predoc_pipeline import pipeline
from predoc_pipeline.boards.config import load_preferences
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.urls import url_hash
from predoc_pipeline.models import Discipline, Location, PredocListing
from predoc_pipeline.publish.bot import _handle_tap
from predoc_pipeline.publish.feedback import FeedbackStore, generate_key
from predoc_pipeline.routing import Router
from predoc_pipeline.settings import Settings


def _listing(i: int, *, doctoral: bool = False) -> PredocListing:
    title = (f"PhD Researcher in Applied Economics {i}" if doctoral
             else f"Research Assistant in Economics {i}")
    return PredocListing(
        title=title, institution=f"University {i}",
        location=Location(country="Germany", city="Berlin"),
        disciplines=[Discipline.APPLIED_MICRO],
        summary="Research on labor economics, using quantitative methods.",
        apply_url=f"https://example.org/position/{i}",
        source_url=f"https://example.org/position/{i}",
    )


def _assert_channel_card(sent: dict, listing: PredocListing) -> None:
    buttons = sent["keyboard"]["inline_keyboard"][0]
    assert [b["text"] for b in buttons] == ["Open listing", "🔖 Save"]
    assert buttons[0]["url"] == listing.apply_url
    assert buttons[1]["callback_data"] == f"fav:save:{url_hash(listing.apply_url)[:16]}"
    assert "new research positions" not in sent["html"]
    assert "new predoc listings" not in sent["html"]


def test_high_volume_new_positions_remain_separate_even_above_digest_threshold(tmp_path):
    db_path = tmp_path / "state.db"
    init(db_path)
    settings = Settings(
        _env_file=None, telegram_bot_token="offline",
        telegram_public_channel_id="@existing", telegram_digest_threshold=1,
        telegram_bot_username="",
    )
    tg = Mock()
    tg.send_message.side_effect = [401, 402, 403]
    with Database(db_path) as db:
        listings = [_listing(i) for i in range(3)]
        accepted = [(
            db.insert_listing(pipeline._listing_row(job, source="test", signature=None)), job
        ) for job in listings]
        stats = pipeline.RunStats()
        pipeline._broadcast(accepted, tg, settings, db, stats)
        assert tg.send_message.call_count == 3
        for i, (lid, job) in enumerate(accepted):
            sent = tg.send_message.call_args_list[i].kwargs
            assert sent["chat_id"] == "@existing"
            assert job.title in sent["html"]
            for other in listings:
                if other is not job:
                    assert other.title not in sent["html"]
            _assert_channel_card(sent, job)
            assert db.listing(lid)["telegram_message_id"] == 401 + i
        assert stats.published == 3


def test_historical_phds_have_separate_receipts_and_save_controls(tmp_path):
    db_path = tmp_path / "state.db"
    init(db_path)
    settings = Settings(
        _env_file=None, telegram_bot_token="offline",
        telegram_public_channel_id="@existing", telegram_bot_username="",
        telegram_non_us_econ_phd_enabled=True,
    )
    prefs = load_preferences(Path(__file__).resolve().parents[2] / "config/preferences.toml")
    tg = Mock()
    tg.send_message.side_effect = [501, 502]
    with Database(db_path) as db:
        jobs = [_listing(i, doctoral=True) for i in range(2)]
        ids = []
        for job in jobs:
            lid = db.insert_listing(pipeline._listing_row(job, source="test", signature=None))
            db.mark_published(lid, None, x_post_id=f"prior-tweet-{lid}")
            ids.append(lid)
        before = [db.listing(lid)["published_at"] for lid in ids]
        pipeline._publish_non_us_econ_phds(
            db, tg, settings, pipeline.RunStats(), Router(prefs), prefs,
            fresh_ids=set(), verify=False,
        )
        assert tg.send_message.call_count == 2
        for i, (lid, job) in enumerate(zip(ids, jobs, strict=True)):
            sent = tg.send_message.call_args_list[i].kwargs
            assert "Previously collected" in sent["html"]
            assert "Current availability" in sent["html"]
            assert job.title in sent["html"]
            assert jobs[1 - i].title not in sent["html"]
            _assert_channel_card(sent, job)
            row = db.listing(lid)
            assert row["telegram_message_id"] == 501 + i
            assert row["published_at"] == before[i]
            assert row["x_post_id"] == f"prior-tweet-{lid}"
            assert db.telegram_state(lid) == "confirmed"


def test_channel_save_callback_uses_tapping_user_not_public_chat(tmp_path):
    store = FeedbackStore(tmp_path / "favorites.json", key=generate_key())
    bot = Mock()
    summary = {"ignored": 0, "taps": 0}
    prefix = "a" * 16
    def tap(identifier, user, action):
        return {"id": identifier, "from": {"id": user},
                "message": {"chat": {"id": -10012345, "type": "channel"},
                            "message_id": 24},
                "data": action}
    for identifier, user in [("first", 991), ("repeat", 991), ("second", 992)]:
        _handle_tap(bot, tap(identifier, user, f"fav:save:{prefix}"), {}, store, set(), summary)
    assert store.favorites(991) == [prefix]
    assert store.favorites(992) == [prefix]
    assert "-10012345" not in store.data["favorites"]
    assert bot.call.call_count == 3
    assert all(call.args[0] == "answerCallbackQuery" for call in bot.call.call_args_list)
