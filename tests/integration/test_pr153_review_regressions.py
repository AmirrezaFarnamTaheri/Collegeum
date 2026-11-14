"""Regression coverage for PR #153 CodeRabbit findings."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from predoc_pipeline import pipeline
from predoc_pipeline.boards.config import Preferences, load_preferences
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.textproc import telegram_visible_length
from predoc_pipeline.models import Discipline, Location, PredocListing
from predoc_pipeline.publish.bot import _favorite_screen, _handle_message, _handle_tap
from predoc_pipeline.publish.feedback import FeedbackStore
from predoc_pipeline.publish.interactions import private_message
from predoc_pipeline.routing import Channel, Router
from predoc_pipeline.settings import Settings


def _listing(**kwargs):
    data = {
        "title": "PhD Economist",
        "institution": "Example University",
        "location": Location(country="Germany", city="Berlin"),
        "disciplines": [Discipline.APPLIED_MICRO],
        "summary": "Doctoral researcher in economics.",
        "apply_url": "https://example.edu/jobs/1",
        "source_url": "https://example.edu/jobs/1",
    }
    data.update(kwargs)
    return PredocListing(**data)


def test_completed_phd_qualification_is_not_a_doctoral_vacancy():
    job = _listing(min_degree="phd", summary="A PhD in economics is required.")
    assert Router(Preferences()).position_kind(
        job.title, job.summary, min_degree=job.min_degree,
    ) == "research"
    assert Router(Preferences()).destinations(job) == frozenset({Channel.WEB})


def test_enrollment_is_not_mistaken_for_general_admissions():
    job = _listing(summary="The successful candidate enrolls in the graduate programme in economics.")
    assert Channel.TELEGRAM in Router(Preferences()).destinations(job)
    admissions = _listing(summary="Applications for the graduate programme in economics are invited.")
    assert Channel.TELEGRAM not in Router(Preferences()).destinations(admissions)


@pytest.mark.parametrize("country,city", [
    ("N/A", None), ("an unknown country", None), ("remote", None), ("", None),
    ("United States", "Boston"),
])
def test_phd_workplace_must_be_recognized_non_us(country, city):
    job = _listing(location=Location(country=country, city=city))
    assert Channel.TELEGRAM not in Router(Preferences()).destinations(job)


def test_favorites_owner_limit_rejects_without_mutating_state(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.json")
    store.data["favorites"] = {str(i): {} for i in range(1, 10001)}
    with pytest.raises(ValueError, match="owner limit"):
        store.add_favorite(10001, "a" * 16)
    assert len(store.data["favorites"]) == 10000
    assert store.add_favorite(1, "a" * 16)
    store.save()
    assert FeedbackStore(tmp_path / "feedback.json").favorites(1) == ["a" * 16]


def test_polling_start_favorite_deep_link_reaches_handler(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.json")
    calls = []
    bot = SimpleNamespace(send=lambda *args: calls.append(args))
    message = {"chat": {"id": 123, "type": "private"}, "from": {"id": 123},
               "text": "/start f_" + "a" * 16}
    summary = {"received": 0, "commands": 0, "ignored": 0}
    assert private_message(bot, message, store, SimpleNamespace(), [], summary) is False
    _handle_message(bot, message, [], store, set(), summary)
    assert store.favorites(123) == ["a" * 16]
    assert len(calls) == 1
    assert "\n\n" in calls[0][1]
    assert "\\n" not in calls[0][1]


def test_favorites_screen_paginates_without_overflow_and_callbacks_navigate(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.json")
    rows = []
    for i in range(35):
        prefix = f"{i:016x}"
        store.add_favorite(123, prefix)
        rows.append({
            "url_hash": prefix + "0" * 48,
            "title": "A" * 120,
            "institution": "B" * 100,
            "closed_at": None,
            "expired_at": None,
            "apply_url": f"https://example.edu/jobs/{i}",
        })
    first, keyboard = _favorite_screen(store, 123, rows)
    assert telegram_visible_length(first) < 4096
    assert "Page 1 of" in first
    assert any(button.get("callback_data") == "fav:page:1"
               for group in keyboard["inline_keyboard"] for button in group)
    calls = []
    bot = SimpleNamespace(call=lambda method, args: calls.append((method, args)))
    callback = {"id": "favorite-page", "from": {"id": 123},
                "message": {"chat": {"id": 123, "type": "private"}, "message_id": 77},
                "data": "fav:page:1"}
    summary = {"ignored": 0, "taps": 0}
    _handle_tap(bot, callback, {}, store, set(), summary, rows=rows)
    rendered = [payload for method, payload in calls if method == "editMessageText"][0]
    assert "Page 2 of" in rendered["text"]
    assert telegram_visible_length(rendered["text"]) < 4096
    assert store.favorites(123)


def test_hidden_phd_does_not_get_historical_telegram_backfill(tmp_path):
    path = tmp_path / "listings.db"
    init(path)
    prefs = load_preferences(Path(__file__).resolve().parents[2] / "config/preferences.toml")
    job = _listing(title="PhD Researcher in Economics")
    config = Settings(_env_file=None, telegram_bot_token="offline-token",
                      telegram_public_channel_id="@example",
                      telegram_bot_username="collegeum_example_bot",
                      telegram_non_us_econ_phd_enabled=True)
    with Database(path) as db:
        lid = db.insert_listing(pipeline._listing_row(job, source="test", signature=None))
        db.mark_published(lid, None)
        stored = db.listing(lid)
        hidden = {stored["url_hash"]}
        calls = []
        sender = SimpleNamespace(send_message=lambda **kw: calls.append(kw))
        pipeline._publish_non_us_econ_phds(
            db, sender, config, pipeline.RunStats(), Router(prefs), prefs,
            fresh_ids=set(), hidden=hidden, verify=False,
        )
        assert calls == []
        assert db.telegram_state(lid) == "not_attempted"
