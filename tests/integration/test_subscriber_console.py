"""End-to-end private subscriber and admin flows against a fake Telegram API."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx

from predoc_pipeline.ingest.career import (
    classify_career,
    load_career,
    parse_iran_jobs,
    parse_remote_jobs,
    save_career,
)
from predoc_pipeline.ingest.rotation import scheduled_sources
from predoc_pipeline.publish.admin import admin_id
from predoc_pipeline.publish.bot import telegram_sync
from predoc_pipeline.publish.feedback import FeedbackStore, generate_key
from predoc_pipeline.publish.subscriptions import dispatch, eligible, matching
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


def test_delivery_intents_prevent_replay_after_unknown_acceptance(tmp_path):
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
    api = API()
    api.error = "lost response"
    with httpx.Client(transport=httpx.MockTransport(api.handler)) as client:
        from predoc_pipeline.publish.telegram import TelegramClient

        tg = TelegramClient(bot_token="test", client=client)
        result = dispatch(store, tg, [], [job], sleep=lambda _: None)
        assert result["uncertain"] == 1
        assert len(api.sent(101)) == 1
        assert dispatch(store, tg, [], [job])["sent"] == 0
    saved = FeedbackStore.from_settings(cfg)
    assert saved.subscriber(101)["deliveries"]["career:123"]["state"] == "uncertain"
    saved.resolve_delivery(101, "career:123", confirmed_absent=True)
    saved.save()
    api.error = None
    with httpx.Client(transport=httpx.MockTransport(api.handler)) as client:
        from predoc_pipeline.publish.telegram import TelegramClient

        tg = TelegramClient(bot_token="test", client=client)
        assert dispatch(saved, tg, [], [job], sleep=lambda _: None)["sent"] == 1
        assert dispatch(saved, tg, [], [job], sleep=lambda _: None)["sent"] == 0


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
    assert classify_career("Data Scientist") == "data_scientist"
    assert classify_career("Assistant accountant") is None
    jobs = parse_remote_jobs({"jobs": [
        {"jobTitle": "Data Analyst", "jobGeo": "USA", "url": "https://jobicy.com/jobs/1"},
        {"jobTitle": "Data Scientist", "jobGeo": "Anywhere",
         "url": "https://jobicy.com/jobs/2", "companyName": "A"},
    ]})
    assert len(jobs) == 1 and jobs[0]["scope"] == "remote"
    html = ('<article><a href="/companies/sample/jobs/123-data-analyst">'
            'تحلیلگر داده</a></article>')
    iran = parse_iran_jobs(html)
    assert len(iran) == 1 and iran[0]["scope"] == "iran"
    state_path = tmp_path / "jobs.ndjson"
    assert save_career(state_path, [], jobs + iran) == 2
    assert save_career(state_path, load_career(state_path), jobs + iran) == 0
    assert len(load_career(state_path)) == 2


def test_three_hour_rotation_covers_every_source_with_two_complementary_slots():
    sources = [SimpleNamespace(name=f"source-{i}", enabled=True) for i in range(9)]
    sources.append(SimpleNamespace(name="disabled", enabled=False))
    a = scheduled_sources(sources, timestamp=datetime(2026, 10, 11, 0, tzinfo=UTC))
    b = scheduled_sources(sources, timestamp=datetime(2026, 10, 11, 3, tzinfo=UTC))
    assert not (a & b)
    assert a | b == {f"source-{i}" for i in range(9)}
    assert abs(len(a) - len(b)) <= 1
