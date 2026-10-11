"""End-to-end private subscriber and admin flows against a fake Telegram API."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx

from predoc_pipeline.ingest.career import (
    classify_career,
    load_career,
    poll_career,
    parse_iran_jobs,
    parse_remote_jobs,
    save_career,
)
from predoc_pipeline.ingest.rotation import SCHEDULE_INTERVAL_HOURS, scheduled_sources
from predoc_pipeline.publish.admin import admin_id
from predoc_pipeline.publish.bot import telegram_sync
from predoc_pipeline.publish.feedback import FeedbackStore, generate_key, load_chat_state
from predoc_pipeline.publish.private_delivery import plan_batch, send_batch
from predoc_pipeline.publish.subscriptions import eligible, matching
from predoc_pipeline.settings import Settings


class API:
    def __init__(self, updates=()):
        self.updates = list(updates)
        self.calls = []
        self.error = None

    def handler(self, request):
        method = str(request.url).split("/")[-1]
        body = json.loads(request.content)
        self.calls.append((method, body))
        if method == "getUpdates":
            result = [x for x in self.updates if x["update_id"] >= body.get("offset", 0)]
        elif method == "sendMessage":
            if self.error is not None:
                raise httpx.ReadTimeout("response lost", request=request)
            result = {"message_id": len(self.calls)}
        else:
            result = True
        return httpx.Response(200, json={"ok": True, "result": result})

    def sent(self, chat_id=None):
        return [
            data for method, data in self.calls
            if method == "sendMessage"
            and (chat_id is None or data["chat_id"] == str(chat_id))
        ]


def settings(tmp_path, admin_id_value=""):
    return Settings(
        _env_file=None, telegram_bot_token="test",
        telegram_public_channel_id="", telegram_admin_chat_id=admin_id_value,
        feedback_encryption_key=generate_key(),
        feedback_path=str(tmp_path / "feedback.json"),
        telegram_state_path=str(tmp_path / "updates.json"),
        state_path=str(tmp_path / "journal.ndjson"),
        seen_state_path=str(tmp_path / "seen.ndjson"),
        db_path=str(tmp_path / "db.sqlite"),
        career_state_path=str(tmp_path / "career.ndjson"),
        dashboard_json=str(tmp_path / "docs/listings.json"),
        feed_path=str(tmp_path / "docs/feed.xml"),
    )


def run(settings_value, api):
    with httpx.Client(transport=httpx.MockTransport(api.handler)) as client:
        return telegram_sync(settings_value, http_client=client, sleep=lambda _: None)


def message(number, user, command):
    return {"update_id": number, "message": {
        "chat": {"id": user, "type": "private"}, "from": {"id": user},
        "text": command, "message_id": number,
    }}


def tap(number, user, callback, callback_id=None):
    return {"update_id": number, "callback_query": {
        "id": callback_id or f"button{number}", "from": {"id": user},
        "data": callback,
        "message": {"message_id": 101, "chat": {"id": user, "type": "private"}},
    }}


def test_private_subscription_and_replay_isolation(tmp_path):
    cfg = settings(tmp_path)
    api = API([message(1, 101, "/start"), tap(2, 101, "sub:t:predoc"),
               message(3, 202, "/settings"), tap(4, 101, "sub:t:predoc",
                                                  callback_id="button2")])
    run(cfg, api)
    store = FeedbackStore.from_settings(cfg)
    assert "predoc" in store.subscriber(101)["topics"]
    assert store.subscriber(202) is None
    assert "predoc" not in (store.subscriber(202) or {}).get("topics", {})
    assert len(api.sent(202)) == 1
    assert not (tmp_path / "feedback.json").exists()
    assert (tmp_path / "feedback.enc").exists()


def test_admin_confirmation_is_private_and_replay_safe(tmp_path):
    cfg = settings(tmp_path, "99")
    api = API([
        tap(1, 101, "adm:confirm:pause"),
        message(2, 99, "/admin"),
        tap(3, 99, "adm:confirm:pause"),
        tap(4, 99, "adm:confirm:pause", callback_id="button3"),
    ])
    run(cfg, api)
    store = FeedbackStore.from_settings(cfg)
    assert store.data["ops"]["paused"]
    assert len(store.data["ops"]["audit"]) == 1
    assert admin_id(cfg) == 99
    assert not api.sent(101)


def test_stop_erases_subscriber_and_prevents_later_alerts(tmp_path):
    cfg = settings(tmp_path)
    api = API([tap(1, 101, "sub:t:predoc"), message(2, 101, "/stop")])
    run(cfg, api)
    assert FeedbackStore.from_settings(cfg).subscriber(101) is None


def test_two_phase_delivery_requires_checkpoint_and_reconciles_uncertain(tmp_path):
    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "data_analyst")
    store.toggle_subscription(101, "scopes", "remote")
    before = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    store.subscriber(101)["topics"]["data_analyst"] = before
    store.subscriber(101)["scopes"]["remote"] = before
    store.save()
    job = {
        "key": "career:123", "category": "data_analyst", "scope": "remote",
        "first_seen_at": datetime.now(UTC).isoformat(),
        "title": "Data Analyst", "url": "https://jobicy.com/jobs/123",
        "employer": "Example", "location": "Anywhere", "source": "Jobicy",
    }
    save_career(cfg.career_state_path, [], [job])
    batch = tmp_path / "private-batch.json"
    assert plan_batch(cfg, path=batch) == 1
    assert FeedbackStore.from_settings(cfg).subscriber(101)[
        "deliveries"]["career:123"]["state"] == "sending"

    api = API()
    api.error = "lost response"
    with httpx.Client(transport=httpx.MockTransport(api.handler)) as client:
        result = send_batch(cfg, path=batch, client=client, sleep=lambda _: None)
        assert result["uncertain"] == 1
        assert len(api.sent(101)) == 1
        assert send_batch(cfg, path=batch, client=client)["sent"] == 0

    saved = FeedbackStore.from_settings(cfg)
    assert saved.subscriber(101)["deliveries"]["career:123"]["state"] == "uncertain"
    assert plan_batch(cfg, path=batch) == 0
    saved.resolve_delivery(101, "career:123", confirmed_absent=True)
    saved.save()
    assert plan_batch(cfg, path=batch) == 1
    api.error = None
    with httpx.Client(transport=httpx.MockTransport(api.handler)) as client:
        assert send_batch(cfg, path=batch, client=client, sleep=lambda _: None)["sent"] == 1
        assert send_batch(cfg, path=batch, client=client, sleep=lambda _: None)["sent"] == 0


def test_non_text_private_update_does_not_block_stop_command(tmp_path):
    cfg = settings(tmp_path)
    api = API([
        {"update_id": 1, "message": {
            "chat": {"id": 101, "type": "private"}, "from": {"id": 101},
            "sticker": {"file_id": "ignored"},
        }},
        message(2, 101, "/stop"),
    ])
    result = run(cfg, api)
    assert result["failed"] == 0
    assert load_chat_state(cfg.telegram_state_path)["offset"] == 3


def test_previews_existing_roles_without_backfilling_notifications():
    now = datetime.now(UTC)
    before = (now - timedelta(hours=2)).isoformat()
    member = {
        "topics": {"data_analyst": now.isoformat()},
        "scopes": {"iran": now.isoformat()},
        "deliveries": {},
    }
    job = {
        "key": "career:old", "category": "data_analyst", "scope": "iran",
        "first_seen_at": before, "url": "https://jobinja.ir/companies/x/jobs/y",
        "title": "Data Analyst", "employer": "Example", "location": "Tehran",
    }
    assert matching(member, [], [job]) == []
    assert len(matching(member, [], [job], preview=True)) == 1


def test_sent_receipt_retention_never_prunes_ambiguous_records(tmp_path):
    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "predoc")
    old = (datetime.now(UTC) - timedelta(days=60)).isoformat()
    store.subscriber(101)["deliveries"] = {
        "academic:old": {"state": "sent", "at": old},
        "academic:unknown": {"state": "uncertain", "at": old},
        "academic:pending": {"state": "sending", "at": old},
    }
    assert store.prune_deliveries() == 1
    assert set(store.subscriber(101)["deliveries"]) == {
        "academic:unknown", "academic:pending",
    }



def test_scope_and_topic_both_needed_and_no_retrospective_delivery():
    now = datetime.now(UTC)
    member = {
        "topics": {"data_analyst": now.isoformat()},
        "scopes": {"iran": now.isoformat()},
        "deliveries": {},
    }
    after = (now + timedelta(seconds=30)).isoformat()
    before = (now - timedelta(minutes=1)).isoformat()
    assert eligible(member, "data_analyst", "iran", after)
    assert not eligible(member, "data_analyst", "remote", after)
    assert not eligible(member, "data_analyst", "iran", before)
    assert not eligible(member, "data_scientist", "iran", after)
    assert matching(member, [], []) == []


def test_career_parsers_and_journal_do_not_conflate_geographies(tmp_path):
    assert classify_career("تحلیلگر داده") == "data_analyst"
    assert classify_career("تحلیل‌گر داده") == "data_analyst"
    assert classify_career("Data Scientist") == "data_scientist"
    assert classify_career("Assistant accountant") is None
    jobs = parse_remote_jobs({"jobs": [
        {"jobTitle": "Data Analyst", "jobGeo": "USA", "url": "https://jobicy.com/jobs/1"},
        {"jobTitle": "Data Scientist", "jobGeo": "Anywhere",
         "url": "https://jobicy.com/jobs/2", "companyName": "A"},
    ]})
    assert len(jobs) == 1 and jobs[0]["scope"] == "remote"
    denied = parse_remote_jobs({"jobs": [
        {"jobTitle": "Data Analyst", "jobGeo": "Anywhere excluding Iran",
         "url": "https://jobicy.com/jobs/3"},
    ]})
    assert denied == []
    html = ('<article><a href="/companies/sample/jobs/123-data-analyst">'
            'تحلیلگر داده</a></article>')
    iran = parse_iran_jobs(html)
    assert len(iran) == 1 and iran[0]["scope"] == "iran"
    state_path = tmp_path / "jobs.ndjson"
    assert save_career(state_path, [], jobs + iran) == 2
    assert save_career(state_path, load_career(state_path), jobs + iran) == 0
    assert len(load_career(state_path)) == 2


def test_four_hour_rotation_covers_every_source_with_two_complementary_slots():
    sources = [SimpleNamespace(name=f"source-{i}", enabled=True) for i in range(9)]
    sources.append(SimpleNamespace(name="disabled", enabled=False))
    a = scheduled_sources(sources, timestamp=datetime(2026, 10, 11, 0, tzinfo=UTC))
    b = scheduled_sources(sources, timestamp=datetime(2026, 10, 11, 4, tzinfo=UTC))
    assert not (a & b)
    assert a | b == {f"source-{i}" for i in range(9)}
    assert abs(len(a) - len(b)) <= 1


def test_pipeline_schedule_matches_source_rotation_interval():
    """Prevent cron and cohort rotation from drifting apart."""
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/pipeline.yml").read_text(encoding="utf-8")
    assert SCHEDULE_INTERVAL_HOURS == 4
    assert 'cron: "0 */4 * * *"' in workflow


def test_remote_feed_follows_bounded_cursor_without_duplicate_alerts(tmp_path):
    from types import SimpleNamespace

    pages = [
        {"jobs": [
            {"jobTitle": "Data Analyst", "jobGeo": "Anywhere",
             "url": "https://jobicy.com/jobs/first", "companyName": "A"},
        ], "nextCursor": "opaque-token", "success": True},
        {"jobs": [
            {"jobTitle": "Data Scientist", "jobGeo": "Global",
             "url": "https://jobicy.com/jobs/second", "companyName": "B"},
        ], "nextCursor": None, "success": True},
    ]

    class Client:
        def __init__(self):
            self.calls = []

        def get(self, url):
            self.calls.append(url)
            return SimpleNamespace(ok=True, text=json.dumps(pages[len(self.calls) - 1]))

    client = Client()
    saved = tmp_path / "careers.ndjson"
    added, errors = poll_career(
        saved, client=client, needs_iran=False, needs_remote=True,
    )
    assert not errors
    assert added == 2
    assert len(load_career(saved)) == 2
    assert len(client.calls) == 2
    assert "cursor=opaque-token" in client.calls[1]


def test_remote_feed_ignores_repeated_cursor(tmp_path):
    from types import SimpleNamespace

    class Client:
        def __init__(self):
            self.calls = []

        def get(self, url):
            self.calls.append(url)
            return SimpleNamespace(ok=True, text=json.dumps({
                "success": True, "jobs": [], "nextCursor": "same-token",
            }))

    client = Client()
    added, errors = poll_career(
        tmp_path / "career.ndjson", client=client,
        needs_iran=False, needs_remote=True,
    )
    assert added == 0
    assert len(client.calls) == 2
    assert any("cursor" in e for e in errors)


def test_planner_never_reserves_without_bot_credentials(tmp_path):
    import pytest

    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "data_analyst")
    store.toggle_subscription(101, "scopes", "remote")
    store.save()
    cfg.telegram_bot_token = ""
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        plan_batch(cfg, path=tmp_path / "private-batch.json")
    assert FeedbackStore.from_settings(cfg).subscriber(101)["deliveries"] == {}


def test_batch_write_failure_cannot_persist_orphan_send_intents(tmp_path, monkeypatch):
    import pytest
    from predoc_pipeline.publish import private_delivery

    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "data_analyst")
    store.toggle_subscription(101, "scopes", "remote")
    before = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    store.subscriber(101)["topics"]["data_analyst"] = before
    store.subscriber(101)["scopes"]["remote"] = before
    store.save()
    save_career(cfg.career_state_path, [], [{
        "key": "career:example", "title": "Data Analyst", "category": "data_analyst",
        "scope": "remote", "url": "https://jobicy.com/jobs/example",
        "employer": "Example", "location": "Anywhere", "source": "Jobicy",
    }])

    def disk_failure(*_args, **_kwargs):
        raise OSError("outbox storage unavailable")

    monkeypatch.setattr(private_delivery, "_save_batch", disk_failure)
    with pytest.raises(OSError, match="outbox storage"):
        plan_batch(cfg, path=tmp_path / "batch.json")
    assert FeedbackStore.from_settings(cfg).subscriber(101)["deliveries"] == {}


def test_career_journal_rejects_untrusted_scope_and_oversized_urls(tmp_path):
    import pytest

    from predoc_pipeline.ingest.career import _job

    assert _job(
        url="https://jobicy.com/jobs/" + "x" * 1050, title="Data Analyst",
        employer="Example", location="Anywhere", source="Jobicy", scope="remote",
    ) is None
    path = tmp_path / "jobs.ndjson"
    path.write_text(json.dumps({
        "key": "career:one", "category": "data_analyst", "scope": "arbitrary",
        "url": "https://jobicy.com/jobs/one", "title": "Data Analyst",
        "employer": "Example", "location": "Elsewhere", "source": "Test",
        "first_seen_at": datetime.now(UTC).isoformat(),
    }) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid career category or scope"):
        load_career(path)


def test_polling_writes_source_health_without_personal_details(tmp_path):
    from types import SimpleNamespace

    class FailJobinja:
        def get(self, _url):
            return SimpleNamespace(ok=False, error="HTTP 503", status=503)

    journal = tmp_path / "career.ndjson"
    health = tmp_path / "career_health.json"
    count, errors = poll_career(
        journal, client=FailJobinja(), needs_remote=False, needs_iran=True,
        health_path=health, slot=0,
    )
    assert count == 0
    assert len(errors) == 1
    data = json.loads(health.read_text("utf-8"))
    assert data["sources"]["jobinja"]["fetched"] == 1
    assert data["sources"]["jobinja"]["accepted"] == 0
    assert data["sources"]["jobicy"]["requested"] is False
    assert "subscribers" not in data
    assert "chat_id" not in health.read_text("utf-8")


def test_permanent_telegram_bad_request_is_quarantined_until_reconciled(tmp_path):
    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "data_analyst")
    store.toggle_subscription(101, "scopes", "remote")
    prior = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    store.subscriber(101)["topics"]["data_analyst"] = prior
    store.subscriber(101)["scopes"]["remote"] = prior
    store.save()
    save_career(cfg.career_state_path, [], [{
        "key": "career:bad", "category": "data_analyst", "scope": "remote",
        "title": "Data Analyst", "url": "https://jobicy.com/jobs/bad",
        "employer": "Example", "location": "Anywhere", "source": "Jobicy",
    }])
    batch = tmp_path / "batch.json"
    assert plan_batch(cfg, path=batch) == 1
    with httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(400, text="can't parse entities")
    )) as client:
        result = send_batch(cfg, path=batch, client=client, sleep=lambda _: None)
    assert result["failed"] == 1
    assert FeedbackStore.from_settings(cfg).subscriber(101)[
        "deliveries"]["career:bad"]["state"] == "rejected"
    assert plan_batch(cfg, path=batch) == 0
