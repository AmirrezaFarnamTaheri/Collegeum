"""Durable publication reconciliation and current-policy recovery regressions."""

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from predoc_pipeline import pipeline, state
from predoc_pipeline.boards.config import Preferences
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.urls import url_hash
from predoc_pipeline.models import RawItem
from predoc_pipeline.policy import Policy
from predoc_pipeline.settings import Settings


def record(**changes):
    url = "https://example.org/job/one"
    row = {
        "id": 42, "url_hash": url_hash(url),
        "title": "Research Assistant in Economics",
        "institution": "Example University", "source_url": url, "apply_url": url,
        "source": "test", "country": "United Kingdom", "is_remote": False,
        "first_seen_at": "2026-10-12T00:00:00Z",
        "last_seen_at": "2026-10-12T00:00:00Z",
        "summary": "Economics research and statistical analysis.", "language": "en",
        "visa_sponsorship_status": "unknown", "disciplines": ["economics"],
        "model_confidence": 0.9, "rule_score": 0.9, "confidence": 0.9,
        "status": "pending",
    }
    row.update(changes)
    return row


def settings_for(root):
    return Settings(
        _env_file=None, db_path=str(root / "cache.db"),
        state_path=str(root / "listings.ndjson"),
        seen_state_path=str(root / "seen.ndjson"),
        dashboard_json=str(root / "listings.json"),
        health_json=str(root / "health.json"), feed_path=str(root / "feed.xml"),
        dlq_path=str(root / "dlq.json"), feedback_path=str(root / "feedback.json"),
        telegram_state_path=str(root / "telegram.json"),
        preferences_config=str(root / "preferences.toml"),
        sources_config=str(root / "sources.toml"),
        extraction_backend="heuristic", telegram_bot_token="offline-test-token",
        telegram_public_channel_id="123", x_broadcast_enabled=False,
        empty_run_alert_threshold=999,
    )


def test_newer_journal_delivery_ack_wins_over_stale_pending_sqlite(tmp_path):
    settings = settings_for(tmp_path)
    init(settings.db_path)
    with Database(settings.db_path) as db:
        db.import_rows([record()])
        ack = record(status="published", telegram_message_id=777,
                     published_at="2026-10-12T01:00:00Z")
        Path(settings.state_path).write_text(json.dumps(ack) + "\n")
        state.restore_if_needed(db, settings.state_path)
        row = db.listing(42)
        assert row["status"] == "published"
        assert row["telegram_message_id"] == 777
        state.write_journal(db, settings.state_path)
    restored = state.read_journal(settings.state_path)[0]
    assert restored["status"] == "published"
    assert restored["telegram_message_id"] == 777


def test_older_journal_does_not_erase_newer_sqlite_delivery_ack(tmp_path):
    settings = settings_for(tmp_path)
    init(settings.db_path)
    with Database(settings.db_path) as db:
        db.import_rows([record(
            status="published", telegram_message_id=777,
            published_at="2026-10-12T01:00:00Z",
        )])
        Path(settings.state_path).write_text(json.dumps(record()) + "\n")
        state.restore_if_needed(db, settings.state_path)
        assert db.listing(42)["status"] == "published"
        assert db.listing(42)["telegram_message_id"] == 777


def test_conflicting_remote_acknowledgements_fail_closed_without_overwrite(tmp_path):
    settings = settings_for(tmp_path)
    init(settings.db_path)
    with Database(settings.db_path) as db:
        db.import_rows([record(
            status="published", telegram_message_id=777,
            published_at="2026-10-12T01:00:00Z",
        )])
        newer = record(status="published", telegram_message_id=778,
                       published_at="2026-10-12T02:00:00Z")
        Path(settings.state_path).write_text(json.dumps(newer) + "\n")
        with pytest.raises(ValueError, match="conflicting.*acknowledg"):
            state.restore_if_needed(db, settings.state_path)
        assert db.listing(42)["telegram_message_id"] == 777
        assert state.read_journal(settings.state_path)[0]["telegram_message_id"] == 778


def test_pending_publication_rechecks_latest_employer_policy(tmp_path):
    settings = settings_for(tmp_path)
    prefs = Preferences()
    prefs.enrich.fetch_details = False
    prefs.filters.excluded_employers = ["Example University"]
    init(settings.db_path)
    with Database(settings.db_path) as db:
        db.import_rows([record()])
        assert Policy(prefs).check_stored(db.listing(42)) == "excluded-employer"
    calls = []

    def respond(request):
        calls.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 777}})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client, (
        patch.object(pipeline, "load_preferences", return_value=prefs)
    ), patch.object(pipeline, "load_sources", return_value=[]), (
        patch.object(pipeline, "gather", return_value=([], {}))
    ):
        stats = pipeline.run(settings, sync_telegram=False, telegram_client=client)

    with Database(settings.db_path) as db:
        row = db.listing(42)
        assert row["status"] != "published"
        assert row["closed_at"] is None  # preference changes must remain reversible
    assert stats.published == 0
    assert "sendMessage" not in calls


def test_explicit_board_closure_evidence_updates_matching_published_listing(tmp_path):
    settings = settings_for(tmp_path)
    init(settings.db_path)
    with Database(settings.db_path) as db:
        db.import_rows([record(status="published", telegram_message_id=777,
                               published_at="2026-10-12T01:00:00Z")])
        item = RawItem(
            source="test", source_url=record()["source_url"],
            title=record()["title"], text="This position has been filled.",
            hints={"board": True, "reject": "filled-or-closed"},
        )
        assert pipeline._pre_extract(item, db=db, stats=pipeline.RunStats()) is None
        assert db.listing(42)["closed_at"]
        assert db.seen(url_hash(item.source_url))["decision"] == "rejected"


def test_unrelated_same_title_board_closure_does_not_close_other_listing(tmp_path):
    settings = settings_for(tmp_path)
    init(settings.db_path)
    with Database(settings.db_path) as db:
        db.import_rows([record(status="published", telegram_message_id=777,
                               published_at="2026-10-12T01:00:00Z")])
        item = RawItem(
            source="test", source_url="https://example.org/job/two",
            title=record()["title"], text="This different post was filled.",
            hints={"board": True, "reject": "filled-or-closed"},
        )
        assert pipeline._pre_extract(item, db=db, stats=pipeline.RunStats()) is None
        assert db.listing(42)["closed_at"] is None


def test_legacy_v3_rejection_is_reconsidered_under_current_preferences(tmp_path):
    settings = settings_for(tmp_path)
    init(settings.db_path)
    prefs = Preferences()
    item = RawItem(
        source="test", source_url=record()["source_url"],
        title="Predoc in Economics", text="Hiring a predoc in economics.",
        hints={"board": True},
    )
    with Database(settings.db_path) as db:
        policy = Policy(prefs)
        gate, source_key, digest = pipeline._pre_extract(
            item, db=db, stats=pipeline.RunStats(), policy=policy,
        )
        assert gate.passed
        old_hash = digest.rsplit(":", 1)[-1]
        db.mark_seen(source_key, source=item.source, decision="rejected",
                     reason="preferences:region-US",
                     content_hash=f"candidate-v3:{old_hash}")
        result = pipeline._pre_extract(
            item, db=db, stats=pipeline.RunStats(), policy=Policy(prefs),
        )
        assert result is not None, "legacy rejections must be re-evaluated once"


def test_single_board_http_404_holds_pending_without_claiming_permanent_closure(tmp_path):
    settings = settings_for(tmp_path)
    init(settings.db_path)
    with Database(settings.db_path) as db:
        db.import_rows([record()])
        item = RawItem(
            source="test", source_url=record()["source_url"],
            title=record()["title"], text="Detail fetch returned 404",
            hints={
                "board": True, "reject": "filled-or-closed",
                "closed_reason": "link no longer works (HTTP 404)",
            },
        )
        assert pipeline._pre_extract(item, db=db, stats=pipeline.RunStats()) is None
        listing = db.listing(42)
        assert listing["closed_at"] is None
        assert listing["missing_404_observations"] == 1
        prefs = Preferences()
        prefs.enrich.fetch_details = False
        prefs.filters.allow_private_sector = True
        stats = pipeline.RunStats()
        candidates = pipeline._recover_pending([], db, Policy(prefs), stats, set())
        assert len(candidates) == 1
        with patch("predoc_pipeline.boards.collector.check_links", return_value={}):
            assert pipeline._verify_before_sending(candidates, prefs, db, stats) == []

        def now_open(items, _http, **kwargs):
            kwargs["verified_open"].update(items)
            return {}

        with patch("predoc_pipeline.boards.collector.check_links", side_effect=now_open):
            assert len(pipeline._verify_before_sending(candidates, prefs, db, stats)) == 1
        assert db.listing(42)["missing_404_observations"] == 0


def test_uncertain_delivery_checkpoint_survives_pending_journal_replay(tmp_path):
    settings = settings_for(tmp_path)
    init(settings.db_path)
    with Database(settings.db_path) as db:
        db.import_rows([record(status="delivery-uncertain")])
        Path(settings.state_path).write_text(json.dumps(record()) + "\n")
        state.restore_if_needed(db, settings.state_path)
        assert db.listing(42)["status"] == "delivery-uncertain"
        assert db.pending_listings() == []


def test_manual_broadcast_respects_policy_and_persists_recovery_journal(
    tmp_path, monkeypatch,
):
    from predoc_pipeline import cli
    from predoc_pipeline.publish import telegram

    settings = settings_for(tmp_path)
    init(settings.db_path)
    with Database(settings.db_path) as db:
        db.import_rows([record()])

    prefs = Preferences()
    prefs.enrich.fetch_details = False
    prefs.filters.excluded_employers = ["Example University"]
    prefs.filters.allow_private_sector = True
    monkeypatch.setattr(cli, "_settings", lambda: settings)
    monkeypatch.setattr(cli, "load_preferences", lambda _: prefs)

    def deny_telegram(*_args, **_kwargs):
        pytest.fail("manual broadcast must not call Telegram for excluded rows")

    monkeypatch.setattr(telegram, "TelegramClient", deny_telegram)
    cli.broadcast_pending()

    with Database(settings.db_path) as db:
        assert len(db.pending_listings()) == 1
        prefs.filters.excluded_employers = []
        eligible = pipeline._recover_pending(
            [], db, Policy(prefs), pipeline.RunStats(), set(),
        )
    assert len(eligible) == 1  # relaxing a preference restores eligibility
    assert state.read_journal(settings.state_path)[0]["status"] == "pending"


@pytest.mark.parametrize("rejected_in_journal", [False, True])
def test_curated_rejected_listing_cannot_be_resurrected_by_stale_status(
    tmp_path, rejected_in_journal,
):
    settings = settings_for(tmp_path)
    init(settings.db_path)
    published = record(
        status="published", published_at="2026-10-12T01:00:00Z",
        telegram_message_id=777,
    )
    excluded = record(
        status="rejected", published_at="2026-10-12T01:00:00Z",
        telegram_message_id=777,
    )
    cached = published if rejected_in_journal else excluded
    saved = excluded if rejected_in_journal else published
    with Database(settings.db_path) as db:
        db.import_rows([cached])
        Path(settings.state_path).write_text(json.dumps(saved) + "\n")
        state.restore_if_needed(db, settings.state_path)
        assert db.listing(42)["status"] == "rejected"
        assert db.active_listings() == []


def test_newer_committed_fact_corrections_win_over_older_derived_cache(tmp_path):
    settings = settings_for(tmp_path)
    init(settings.db_path)
    corrected = record(
        apply_url="https://example.org/job/correct-application",
        disciplines=["Health Economics", "Econometrics"],
        last_seen_at="2026-10-13T11:00:00Z",
    )
    with Database(settings.db_path) as db:
        db.import_rows([record()])
        Path(settings.state_path).write_text(json.dumps(corrected) + "\n")
        state.restore_if_needed(db, settings.state_path)
        row = db.listing(42)
        assert row["apply_url"] == corrected["apply_url"]
        assert json.loads(row["disciplines"]) == corrected["disciplines"]


def test_older_journal_facts_never_override_newer_local_extraction(tmp_path):
    settings = settings_for(tmp_path)
    init(settings.db_path)
    newer = record(
        apply_url="https://example.org/job/current",
        last_seen_at="2026-10-13T09:00:00Z",
    )
    with Database(settings.db_path) as db:
        db.import_rows([newer])
        Path(settings.state_path).write_text(json.dumps(record()) + "\n")
        state.restore_if_needed(db, settings.state_path)
        assert db.listing(42)["apply_url"] == newer["apply_url"]
