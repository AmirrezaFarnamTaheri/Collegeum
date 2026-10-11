"""End-to-end private subscriber and admin flows against a fake Telegram API."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx

from predoc_pipeline.ingest.career import (
    classify_career,
    load_career,
    parse_iran_jobs,
    parse_remote_jobs,
    poll_career,
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


def test_command_storm_cannot_block_later_unsubscribe(tmp_path):
    from predoc_pipeline.publish.bot import MAX_COMMANDS_PER_SYNC

    cfg = settings(tmp_path)
    updates = [
        tap(1, 101, "sub:t:data_analyst"),
        *[
            message(index, 101, "/settings")
            for index in range(2, MAX_COMMANDS_PER_SYNC + 18)
        ],
        message(MAX_COMMANDS_PER_SYNC + 18, 101, "/stop"),
        tap(MAX_COMMANDS_PER_SYNC + 19, 101, "sub:stop:yes"),
    ]
    result = run(cfg, API(updates))
    assert result["throttled"] > 0
    assert result["failed"] == 0
    assert FeedbackStore.from_settings(cfg).subscriber(101) is None
    assert load_chat_state(cfg.telegram_state_path)["offset"] == MAX_COMMANDS_PER_SYNC + 20


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


def test_stop_requires_confirmation_and_prevents_later_alerts(tmp_path):
    cfg = settings(tmp_path)
    api = API([tap(1, 101, "sub:t:predoc"), message(2, 101, "/stop")])
    run(cfg, api)
    assert FeedbackStore.from_settings(cfg).subscriber(101) is not None
    assert "Unsubscribe?" in api.sent(101)[-1]["text"]
    confirming = API([tap(3, 101, "sub:stop:yes")])
    run(cfg, confirming)
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
    # Hashing preserves cohort identities when the source registry changes.
    augmented = [*sources, SimpleNamespace(name="aaa-new", enabled=True)]
    a2 = scheduled_sources(augmented, timestamp=datetime(2026, 10, 11, 0, tzinfo=UTC))
    assert a2 & {f"source-{i}" for i in range(9)} == a


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
    assert len(errors) == 2
    data = json.loads(health.read_text("utf-8"))
    assert data["sources"]["irantalent"]["fetched"] == 1
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
    assert result["rejected"] == 1
    assert result["failed"] == 0
    assert FeedbackStore.from_settings(cfg).subscriber(101)[
        "deliveries"]["career:bad"]["state"] == "rejected"
    assert plan_batch(cfg, path=batch) == 0


def test_cli_private_backlog_does_not_expose_identifiers_by_default(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from predoc_pipeline import cli

    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "predoc")
    assert store.reserve_delivery(101, "academic:secret-listing-key")
    store.save()
    monkeypatch.setattr(cli, "_settings", lambda: cfg)
    runner = CliRunner()
    safe = runner.invoke(cli.app, ["subscriber-pending"])
    assert safe.exit_code == 0
    assert "sending=1" in safe.output
    assert "secret-listing-key" not in safe.output
    assert "101" not in safe.output
    detailed = runner.invoke(cli.app, ["subscriber-pending", "--show-ids"])
    assert detailed.exit_code == 0
    assert "chat=101" in detailed.output
    assert "academic:secret-listing-key" in detailed.output


def test_jobicy_batch_status_closes_only_confirmed_vacancies(tmp_path):
    from types import SimpleNamespace

    responses = [
        {
            "jobs": [
                {"id": 123, "jobTitle": "Data Analyst", "jobGeo": "Anywhere",
                 "url": "https://jobicy.com/jobs/123"},
                {"id": 124, "jobTitle": "Data Scientist", "jobGeo": "Anywhere",
                 "url": "https://jobicy.com/jobs/124"},
            ], "nextCursor": None, "success": True,
        },
        {
            "jobs": [
                {"id": 123, "status": "closed"},
                {"id": 124, "status": "unknown"},
            ], "success": True,
        },
    ]

    class Client:
        def __init__(self):
            self.calls = []

        def get(self, url):
            self.calls.append(url)
            return SimpleNamespace(
                ok=True, text=json.dumps(responses[len(self.calls) - 1]),
            )

    client = Client()
    journal = tmp_path / "career.ndjson"
    added, errors = poll_career(
        journal, client=client, needs_remote=True, needs_iran=False,
    )
    assert added == 2 and errors == []
    assert len(client.calls) == 2
    assert "status?ids=123%2C124" in client.calls[1]
    jobs = {job["jobicy_id"]: job for job in load_career(journal)}
    assert jobs["123"]["availability"] == "closed"
    assert jobs["124"]["availability"] == "unknown"
    now = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    member = {
        "topics": {"data_analyst": now, "data_scientist": now},
        "scopes": {"remote": now}, "deliveries": {},
    }
    assert [job["jobicy_id"] for job in matching(
        member, [], list(jobs.values()), preview=True,
    )] == ["124"]


def test_unknown_provider_result_never_reopens_confirmed_closed_vacancy(tmp_path):
    from types import SimpleNamespace

    from predoc_pipeline.ingest.career import _verify_remote_status

    closed = {
        "key": "career:closed", "title": "Data Analyst",
        "category": "data_analyst", "scope": "remote",
        "url": "https://jobicy.com/jobs/987", "employer": "Example",
        "location": "Anywhere", "source": "Jobicy",
        "jobicy_id": "987", "availability": "closed",
        "first_seen_at": datetime.now(UTC).isoformat(),
    }

    class Client:
        def get(self, _url):
            return SimpleNamespace(ok=True, text=json.dumps({
                "success": True, "jobs": [{"id": 987, "status": "unknown"}],
            }))

    stats = {"fetched": 0}
    errors = []
    _verify_remote_status(Client(), [closed], [], errors, stats)
    assert errors == []
    assert stats["fetched"] == 1
    assert closed["availability"] == "closed"


def test_private_manual_reconciliation_requires_message_evidence(tmp_path):
    import pytest

    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "predoc")
    assert store.reserve_delivery(101, "academic:pending")
    with pytest.raises(ValueError, match="message ID"):
        store.resolve_delivery(101, "academic:pending", confirmed_sent=True)
    store.resolve_delivery(
        101, "academic:pending", confirmed_sent=True, message_id=456,
    )
    store.resolve_delivery(
        101, "academic:pending", confirmed_sent=True, message_id=456,
    )
    assert store.subscriber(101)["deliveries"]["academic:pending"]["message_id"] == 456
    with pytest.raises(ValueError, match="Cannot overwrite"):
        store.resolve_delivery(
            101, "academic:pending", confirmed_sent=True, message_id=789,
        )
    assert store.reserve_delivery(101, "academic:rejected")
    store.reject_delivery(101, "academic:rejected", status=400)
    with pytest.raises(ValueError, match="explicitly rejected"):
        store.resolve_delivery(
            101, "academic:rejected", confirmed_sent=True, message_id=789,
        )
    store.resolve_delivery(
        101, "academic:rejected", confirmed_absent=True,
    )
    assert "academic:rejected" not in store.subscriber(101)["deliveries"]


def test_geo_exclusions_override_worldwide_eligibility():
    jobs = parse_remote_jobs({"jobs": [
        {"id": 21, "jobTitle": "Data Analyst",
         "jobGeo": "Anywhere; Iran excluded",
         "url": "https://jobicy.com/jobs/excluded"},
        {"id": 22, "jobTitle": "Data Scientist",
         "jobGeo": "Global, no Iran",
         "url": "https://jobicy.com/jobs/no-iran"},
        {"id": 23, "jobTitle": "Data Analyst",
         "jobGeo": "Worldwide",
         "url": "https://jobicy.com/jobs/allowed"},
    ]})
    assert len(jobs) == 1
    assert jobs[0]["jobicy_id"] == "23"


def test_iran_only_remote_is_not_mislabelled_worldwide():
    jobs = parse_remote_jobs({"jobs": [
        {"id": 31, "jobTitle": "Data Analyst", "jobGeo": "Iran",
         "url": "https://jobicy.com/jobs/iran-only"},
        {"id": 32, "jobTitle": "Data Analyst", "jobGeo": "Anywhere",
         "url": "https://jobicy.com/jobs/worldwide"},
    ]})
    assert [job["jobicy_id"] for job in jobs] == ["32"]



def test_compact_native_bot_ui_has_clear_hierarchy_and_safe_callbacks():
    from predoc_pipeline.publish.ui import menu

    home, markup = menu(None)
    assert "Academic roles: 0/3" in home
    assert len(markup["inline_keyboard"]) == 7  # delivery, sources and language rows
    assert "sub:p:academic" in str(markup)
    assert "sub:p:careers" in str(markup)
    assert "sub:p:markets" in str(markup)
    for page in ("academic", "careers", "markets", "delivery", "privacy", "help", "stop"):
        text, keyboard = menu(None, page)
        assert text
        assert len(text) < 4096
        assert any(
            button.get("callback_data") == "sub:p:home"
            for row in keyboard["inline_keyboard"] for button in row
        ) or page == "stop"
        for row in keyboard["inline_keyboard"]:
            for button in row:
                if "callback_data" in button:
                    assert len(button["callback_data"].encode("utf-8")) <= 64


def test_subscriber_language_pause_and_bulk_role_shortcuts(tmp_path):
    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "predoc")
    initial = store.subscriber(101)["topics"]["predoc"]
    assert store.set_topics_group(101, "academic", True)
    assert store.subscriber(101)["topics"]["predoc"] == initial
    assert len(store.subscriber(101)["topics"]) == 3
    assert store.set_paused(101, True)
    assert store.set_language(101, "fa")
    store.save()

    api = API([message(1, 101, "/start")])
    run(cfg, api)
    assert "دانشگاهی" in api.sent(101)[0]["text"]
    assert "متوقف" in api.sent(101)[0]["text"]

    resumed = API([tap(2, 101, "sub:a:resume")])
    run(cfg, resumed)
    saved = FeedbackStore.from_settings(cfg)
    assert not saved.subscriber(101)["paused"]
    assert saved.subscriber(101)["language"] == "fa"

    bulk_off = API([tap(3, 101, "sub:b:academic:off")])
    run(cfg, bulk_off)
    assert FeedbackStore.from_settings(cfg).subscriber(101)["topics"] == {}


def test_paged_latest_uses_one_editable_message_and_no_auto_backfill(tmp_path):
    cfg = settings(tmp_path)
    now = datetime.now(UTC)
    rows = [{
        "key": f"career:paginated{i}", "title": "Data Analyst",
        "employer": f"Company {i}", "location": "Worldwide",
        "category": "data_analyst", "scope": "remote",
        "source": "Jobicy", "url": f"https://jobicy.com/jobs/page-{i}",
    } for i in range(7)]
    assert save_career(cfg.career_state_path, [], rows) == 7
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "data_analyst")
    store.toggle_subscription(101, "scopes", "remote")
    store.subscriber(101)["topics"]["data_analyst"] = (
        now + timedelta(minutes=1)
    ).isoformat()
    store.save()

    listing = API([message(1, 101, "/latest")])
    run(cfg, listing)
    sent = listing.sent(101)
    assert len(sent) == 1
    assert "1 / 2" in sent[0]["text"]
    assert sent[0]["text"].count("jobicy.com/jobs/") == 4

    nxt = API([tap(2, 101, "sub:p:latest:1")])
    run(cfg, nxt)
    edits = [body for method, body in nxt.calls if method == "editMessageText"]
    assert len(edits) == 1
    assert "2 / 2" in edits[0]["text"]
    assert edits[0]["text"].count("jobicy.com/jobs/") == 3
    assert FeedbackStore.from_settings(cfg).subscriber(101)["deliveries"] == {}


def test_irantalent_public_cards_require_explicit_iran_location():
    from predoc_pipeline.ingest.career import parse_irantalent_jobs

    html = """
    <a href="/en/job/data-analyst/184771">
      <h3>Data Analyst</h3><div class="company">Pars Analytics</div>
      <span class="location">Tehran</span>
    </a>
    <a href="/en/job/data-scientist/184772">
      <h3>Data Scientist</h3><span>Dubai</span>
    </a>
    <a href="https://unrelated.example/en/job/data-scientist/184773">
      <h3>Data Scientist</h3><span>Tehran</span>
    </a>
    <a href="/en/job/data-analyst/184774">
      <h3>Data Analyst</h3><span>Outside of Iran</span>
    </a>
    <a href="/en/job/data-analyst/184771">Data Analyst Tehran</a>
    """
    parsed = parse_irantalent_jobs(html)
    assert len(parsed) == 1
    assert parsed[0]["source"] == "IranTalent"
    assert parsed[0]["scope"] == "iran"
    assert parsed[0]["employer"] == "Pars Analytics"
    assert parsed[0]["location"] == "Tehran"
    assert parsed[0]["url"].endswith("/184771")


def test_iran_job_feed_polls_jobinja_and_irantalent_with_health_counts(tmp_path):
    from types import SimpleNamespace

    from predoc_pipeline.ingest.career import IRANTALENT_URL

    class Client:
        def __init__(self):
            self.urls = []

        def get(self, url):
            self.urls.append(url)
            if url == IRANTALENT_URL:
                html = (
                    '<a href="/en/job/data-scientist/184779">'
                    '<h3>Data Scientist</h3><span>Isfahan</span></a>'
                )
            else:
                html = (
                    '<article><a href="/companies/example/jobs/234-data">'
                    'تحلیلگر داده</a></article>'
                )
            return SimpleNamespace(ok=True, text=html, status=200, error=None)

    client = Client()
    journal = tmp_path / "career.ndjson"
    health = tmp_path / "health.json"
    added, errors = poll_career(
        journal, client=client, needs_remote=False, needs_iran=True,
        slot=0, health_path=health,
    )
    assert errors == []
    assert added == 2
    assert len(client.urls) == 2
    providers = {j["source"] for j in load_career(journal)}
    assert providers == {"IranTalent", "Jobinja"}
    status = json.loads(health.read_text("utf-8"))["sources"]
    assert status["irantalent"]["accepted"] == 1
    assert status["jobinja"]["accepted"] == 1


def test_paused_user_is_excluded_from_private_delivery_plan(tmp_path):
    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "data_analyst")
    store.toggle_subscription(101, "scopes", "remote")
    old = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    store.subscriber(101)["topics"]["data_analyst"] = old
    store.subscriber(101)["scopes"]["remote"] = old
    store.set_paused(101, True)
    store.save()
    save_career(cfg.career_state_path, [], [{
        "key": "career:pause", "category": "data_analyst", "scope": "remote",
        "title": "Data Analyst", "employer": "Example",
        "location": "Anywhere", "url": "https://jobicy.com/jobs/pause",
        "source": "Jobicy",
    }])
    assert plan_batch(cfg, path=tmp_path / "batch.json") == 0
    assert FeedbackStore.from_settings(cfg).subscriber(101)["deliveries"] == {}



def test_source_status_panel_shows_only_allowlisted_provider_counts(tmp_path):
    from predoc_pipeline.publish.ui import sources_panel

    missing, keyboard = sources_panel(tmp_path / "missing.json")
    assert "No source-check report" in missing
    assert keyboard["inline_keyboard"][0][0]["callback_data"] == "sub:p:home"

    health = tmp_path / "health.json"
    health.write_text(json.dumps({
        "checked_at": "2026-10-11T12:00:00+00:00",
        "sources": {
            "jobicy": {"requested": True, "fetched": 3, "accepted": 4},
            "jobinja": {"requested": True, "fetched": 1, "accepted": 1},
            "irantalent": {"requested": True, "fetched": 1, "accepted": 2},
            "unexpected_sensitive_key": {
                "requested": True, "fetched": 1, "accepted": 99,
            },
        },
        "errors": ["untrusted error contains a fake password"],
    }), encoding="utf-8")
    text, markup = sources_panel(health)
    assert "Jobicy" in text and "IranTalent" in text and "Jobinja" in text
    assert "unexpected_sensitive_key" not in text
    assert "fake password" not in text
    assert "4 matches" in text
    assert markup["inline_keyboard"][0][0]["callback_data"] == "sub:p:home"
    fa, _ = sources_panel(health, lang="fa")
    assert "وضعیت منابع" in fa


def test_sources_command_and_inline_navigation_share_same_panel(tmp_path):
    cfg = settings(tmp_path)
    health = tmp_path / "health.json"
    health.write_text(json.dumps({
        "checked_at": datetime.now(UTC).isoformat(),
        "sources": {
            "jobicy": {"requested": False, "fetched": 0, "accepted": 0},
            "jobinja": {"requested": True, "fetched": 1, "accepted": 2},
            "irantalent": {"requested": True, "fetched": 1, "accepted": 4},
        },
        "errors": [],
    }), encoding="utf-8")
    cfg.career_health_path = str(health)

    api = API([message(1, 101, "/sources"), tap(2, 101, "sub:p:sources")])
    run(cfg, api)
    assert len(api.sent(101)) == 1
    assert "IranTalent" in api.sent(101)[0]["text"]
    edits = [p for m, p in api.calls if m == "editMessageText"]
    assert len(edits) == 1
    assert "IranTalent" in edits[0]["text"]



def test_private_job_cards_have_action_links_and_manage_alerts(tmp_path):
    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "data_analyst")
    store.toggle_subscription(101, "scopes", "iran")
    previous = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    store.subscriber(101)["topics"]["data_analyst"] = previous
    store.subscriber(101)["scopes"]["iran"] = previous
    store.save()
    url = "https://www.irantalent.com/en/job/data-analyst/184771"
    save_career(cfg.career_state_path, [], [{
        "key": "career:job-card", "title": "Data Analyst",
        "category": "data_analyst", "scope": "iran", "url": url,
        "employer": "Pars", "location": "Tehran", "source": "IranTalent",
    }])
    batch = tmp_path / "private.json"
    assert plan_batch(cfg, path=batch) == 1
    api = API()
    with httpx.Client(transport=httpx.MockTransport(api.handler)) as client:
        result = send_batch(cfg, path=batch, client=client, sleep=lambda _: None)
    assert result["sent"] == 1
    sent = api.sent(101)[0]
    actions = sent["reply_markup"]["inline_keyboard"]
    assert actions[0][0]["url"] == url
    assert actions[1][0]["callback_data"] == "sub:p:home"
    assert len(actions) == 2


def test_pause_after_planning_cancels_unsent_message_intent(tmp_path):
    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "data_scientist")
    store.toggle_subscription(101, "scopes", "remote")
    previous = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    store.subscriber(101)["topics"]["data_scientist"] = previous
    store.subscriber(101)["scopes"]["remote"] = previous
    store.save()
    save_career(cfg.career_state_path, [], [{
        "key": "career:pause-late", "title": "Data Scientist",
        "category": "data_scientist", "scope": "remote",
        "url": "https://jobicy.com/jobs/pause-late",
        "employer": "Example", "location": "Anywhere", "source": "Jobicy",
    }])
    batch = tmp_path / "batch.json"
    assert plan_batch(cfg, path=batch) == 1
    fresh = FeedbackStore.from_settings(cfg)
    fresh.set_paused(101, True)
    fresh.save()
    api = API()
    with httpx.Client(transport=httpx.MockTransport(api.handler)) as client:
        result = send_batch(cfg, path=batch, client=client, sleep=lambda _: None)
    assert result["sent"] == 0
    assert api.sent(101) == []
    assert FeedbackStore.from_settings(cfg).subscriber(101)["deliveries"] == {}


def test_bot_command_scopes_exclude_administration_for_general_users(tmp_path):
    cfg = settings(tmp_path, "99")
    api = API([message(1, 101, "/start")])
    run(cfg, api)
    command_sets = [
        payload for name, payload in api.calls if name == "setMyCommands"
    ]
    assert len(command_sets) == 3
    global_commands = {
        c["command"] for c in command_sets[0]["commands"]
    }
    assert "admin" not in global_commands
    assert "settings" in global_commands
    assert "sources" in global_commands
    fa = command_sets[1]
    assert fa["language_code"] == "fa"
    assert fa["scope"]["type"] == "all_private_chats"
    scoped = command_sets[2]
    assert scoped["scope"] == {"type": "chat", "chat_id": 99}
    assert "admin" in {command["command"] for command in scoped["commands"]}


def test_forged_cross_user_callback_does_not_change_subscriptions(tmp_path):
    cfg = settings(tmp_path)
    forged = tap(1, 202, "sub:t:predoc")
    forged["callback_query"]["message"]["chat"]["id"] = 101
    api = API([forged])
    run(cfg, api)
    store = FeedbackStore.from_settings(cfg)
    assert store.subscriber(101) is None
    assert store.subscriber(202) is None
    assert not api.sent()


def test_poison_career_journal_does_not_block_later_unsubscribe(tmp_path):
    cfg = settings(tmp_path, "99")
    cfg_path = Path(cfg.career_state_path)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text('{"category":"obsolete"}\\n', encoding="utf-8")
    api = API([
        tap(1, 101, "sub:t:data_analyst"),
        message(2, 101, "/latest"),
        message(3, 99, "/admin"),
        tap(4, 99, "adm:cache"),
        message(5, 101, "/stop"),
        tap(6, 101, "sub:stop:yes"),
    ])
    result = run(cfg, api)
    assert result["failed"] == 0
    assert load_chat_state(cfg.telegram_state_path)["offset"] == 7
    assert FeedbackStore.from_settings(cfg).subscriber(101) is None
    assert any("unavailable" in str(m["text"]) for m in api.sent(101))
    assert any(
        "journal unreadable" in str(body["text"])
        for method, body in api.calls if method == "editMessageText"
    )


def test_blocked_bot_is_unsubscribed_without_delivery_failure(tmp_path):
    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "data_analyst")
    store.toggle_subscription(101, "scopes", "remote")
    prior = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    store.subscriber(101)["topics"]["data_analyst"] = prior
    store.subscriber(101)["scopes"]["remote"] = prior
    store.save()
    save_career(cfg.career_state_path, [], [{
        "key": "career:blocked", "category": "data_analyst", "scope": "remote",
        "title": "Data Analyst", "url": "https://jobicy.com/jobs/blocked",
        "employer": "Example", "location": "Anywhere", "source": "Jobicy",
    }])
    batch = tmp_path / "batch.json"
    assert plan_batch(cfg, path=batch) == 1
    with httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(403, text="bot blocked by user")
    )) as client:
        result = send_batch(cfg, path=batch, client=client, sleep=lambda _: None)
    assert result["unsubscribed"] == 1
    assert result["failed"] == result["uncertain"] == 0
    assert FeedbackStore.from_settings(cfg).subscriber(101) is None


def test_paused_subscriber_still_requests_career_discovery(tmp_path):
    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "data_analyst")
    store.toggle_subscription(101, "scopes", "remote")
    store.set_paused(101, True)
    assert store.wants_career("remote")
    assert not store.wants_career("iran")


def test_worldwide_remote_must_not_contain_regional_restrictions():
    from predoc_pipeline.ingest.career import _remote_geo_allowed
    for text in ("Anywhere in the US", "Europe, anywhere in the EU",
                 "Americas, anywhere", "Global - EU only", "Remote in USA"):
        assert not _remote_geo_allowed(text), text
    for text in ("Anywhere", "Worldwide", "Global", "Anywhere in the world"):
        assert _remote_geo_allowed(text), text


def test_persian_geo_boundaries_and_ambiguous_company_names():
    from predoc_pipeline.ingest.career import _iran_location
    assert _iran_location("رقم") is None
    assert _iran_location("Sari Dewi, London") is None
    assert _iran_location("Kish Group, Mumbai") is None
    assert _iran_location("موقعیت: قم") == "قم"
    assert _iran_location("Location: Sari") == "Sari"


def test_paused_remote_feed_and_bilingual_alert_text(tmp_path):
    from predoc_pipeline.publish.subscriptions import render_alert
    job = {
        "category": "data_analyst", "scope": "remote", "title": "Data Analyst",
        "employer": "Example", "location": "Anywhere",
        "source": "Jobicy", "url": "https://jobicy.com/example",
    }
    fa = render_alert(job, "fa")
    assert "تحلیلگر" in fa and "دورکاری" in fa and "مشاهده فرصت" in fa
    assert "View opportunity" in render_alert(job, "en")
    assert '<a href=' not in render_alert({**job, "url": "javascript:alert(1)"})


def test_career_titles_have_narrow_roles_and_plural_support():
    assert classify_career("Data Analysts") == "data_analyst"
    assert classify_career("Data Science Intern") == "data_scientist"
    assert classify_career("Research Associate") is None
    assert classify_career("Product Analyst") is None
    assert classify_career("Management Consultant") == "econ_consulting"


def test_home_warns_when_career_scopes_are_missing(tmp_path):
    from predoc_pipeline.publish.ui import menu
    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "data_analyst")
    home, _keyboard = menu(store.subscriber(101))
    assert "Choose a job market" in home
    store.toggle_subscription(101, "scopes", "iran")
    home, _keyboard = menu(store.subscriber(101))
    assert "Choose a job market" not in home


def test_missed_rotation_slot_catches_up_and_prevents_repeat(tmp_path):
    from predoc_pipeline.ingest.rotation import load_rotation, save_rotation

    sources = [SimpleNamespace(name=f"feed-{i}", enabled=True) for i in range(8)]
    initial = datetime(2026, 10, 11, 0, tzinfo=UTC)
    early = scheduled_sources(sources, timestamp=initial)
    journal = tmp_path / "rotation.json"
    save_rotation(journal, early, timestamp=initial)
    missed = scheduled_sources(
        sources, timestamp=initial + timedelta(hours=8),
        history=load_rotation(journal),
    )
    assert missed == {s.name for s in sources}
    save_rotation(journal, missed, timestamp=initial + timedelta(hours=8))
    repeated = scheduled_sources(
        sources, timestamp=initial + timedelta(hours=8, minutes=5),
        history=load_rotation(journal),
    )
    assert repeated == set()


def test_corrupt_rotation_checkpoint_recovers_without_failure(tmp_path):
    from predoc_pipeline.ingest.rotation import load_rotation

    journal = tmp_path / "rotation.json"
    journal.write_text('{"attempts": ["wrong"]}', encoding="utf-8")
    assert load_rotation(journal)["attempts"] == {}


def test_career_journal_tolerant_mode_preserves_invalid_original(tmp_path):
    journal = tmp_path / "jobs.ndjson"
    valid = {
        "key": "career:good", "category": "data_analyst", "scope": "remote",
        "url": "https://jobicy.com/jobs/good", "title": "Data Analyst",
        "first_seen_at": datetime.now(UTC).isoformat(),
        "employer": "Example", "location": "Anywhere", "source": "Jobicy",
    }
    original = json.dumps(valid) + "\n" + '{"category":"invalid"}\n'
    journal.write_text(original, encoding="utf-8")
    loaded = load_career(journal, tolerant=True)
    assert [item["key"] for item in loaded] == ["career:good"]
    backups = list(tmp_path.glob("jobs.ndjson.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text("utf-8") == original
    assert journal.read_text("utf-8") == original


def test_source_status_distinguishes_idle_error_and_stale(tmp_path):
    from predoc_pipeline.ingest.career import idle_career_health
    from predoc_pipeline.publish.ui import sources_panel

    report = tmp_path / "career-health.json"
    idle_career_health(report)
    text, _ = sources_panel(report)
    assert "Not selected" in text
    damaged = json.loads(report.read_text("utf-8"))
    damaged["sources"]["jobinja"].update({
        "requested": True, "fetched": 1, "accepted": 0, "status": "error",
    })
    report.write_text(json.dumps(damaged), encoding="utf-8")
    text, _ = sources_panel(report)
    assert "Jobinja" in text and "Source error" in text
    damaged["checked_at"] = "2020-01-01T00:00:00+00:00"
    report.write_text(json.dumps(damaged), encoding="utf-8")
    text, _ = sources_panel(report)
    assert "Stale" in text


def test_daily_digest_reserves_multiple_jobs_as_one_checkpointed_message(tmp_path):
    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "data_analyst")
    store.toggle_subscription(101, "scopes", "remote")
    store.set_delivery_preference(101, "delivery_mode", "digest")
    store.set_delivery_preference(101, "daily_limit", 3)
    member = store.subscriber(101)
    prior = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    member["topics"]["data_analyst"] = prior
    member["scopes"]["remote"] = prior
    store.save()
    jobs = [{
        "key": f"career:digest{i}", "category": "data_analyst", "scope": "remote",
        "title": "Data Analyst", "url": f"https://jobicy.com/jobs/digest{i}",
        "employer": "Example", "location": "Anywhere", "source": "Jobicy",
    } for i in range(5)]
    save_career(cfg.career_state_path, [], jobs)
    at = datetime.now(UTC).replace(hour=12, minute=0, second=0)
    batch = tmp_path / "digest-batch.json"
    assert plan_batch(cfg, path=batch, now=at) == 1
    records = json.loads(batch.read_text("utf-8"))
    assert len(records[0]["keys"]) == 3
    assert "daily Collegeum" in records[0]["text"]
    api = API()
    with httpx.Client(transport=httpx.MockTransport(api.handler)) as client:
        counts = send_batch(cfg, path=batch, client=client, sleep=lambda _: None)
    assert counts["sent"] == 3
    assert len(api.sent(101)) == 1
    member = FeedbackStore.from_settings(cfg).subscriber(101)
    assert all(member["deliveries"][key]["state"] == "sent" for key in records[0]["keys"])
    assert plan_batch(cfg, path=batch, now=at) == 0


def test_quiet_hours_prevent_new_intents_without_discarding_jobs(tmp_path):
    cfg = settings(tmp_path)
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "data_analyst")
    store.toggle_subscription(101, "scopes", "remote")
    store.set_delivery_preference(101, "quiet_hours", True)
    previous = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    store.subscriber(101)["topics"]["data_analyst"] = previous
    store.subscriber(101)["scopes"]["remote"] = previous
    store.save()
    save_career(cfg.career_state_path, [], [{
        "key": "career:quiet", "category": "data_analyst", "scope": "remote",
        "title": "Data Analyst", "url": "https://jobicy.com/jobs/quiet",
        "employer": "Example", "location": "Anywhere", "source": "Jobicy",
    }])
    batch = tmp_path / "quiet-batch.json"
    at = datetime.now(UTC).replace(hour=23, minute=0, second=0)
    assert plan_batch(cfg, path=batch, now=at) == 0
    assert FeedbackStore.from_settings(cfg).subscriber(101)["deliveries"] == {}
    assert plan_batch(cfg, path=batch, now=at.replace(hour=12)) == 1


def test_delivery_preferences_are_persistent_and_idempotent(tmp_path):
    cfg = settings(tmp_path)
    api = API([
        tap(1, 101, "sub:d:mode"), tap(2, 101, "sub:d:quiet"),
        tap(3, 101, "sub:d:limit"), tap(4, 101, "sub:p:delivery"),
    ])
    result = run(cfg, api)
    assert result["failed"] == 0
    member = FeedbackStore.from_settings(cfg).subscriber(101)
    assert member["delivery_mode"] == "digest"
    assert member["quiet_hours"] is True
    assert member["daily_limit"] == 10
    assert any(
        "Daily digest" in body["text"]
        for method, body in api.calls if method == "editMessageText"
    )


def test_rotate_key_reencrypts_without_logging_secrets(tmp_path, monkeypatch):
    import pytest
    from cryptography.fernet import Fernet
    from typer.testing import CliRunner

    from predoc_pipeline import cli

    cfg = settings(tmp_path)
    old_key = cfg.feedback_encryption_key
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "predoc")
    store.save()
    new_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("FEEDBACK_NEW_ENCRYPTION_KEY", new_key)
    monkeypatch.setattr(cli, "_settings", lambda: cfg)
    run_result = CliRunner().invoke(cli.app, ["subscriber-rotate-key"])
    assert run_result.exit_code == 0
    assert old_key not in run_result.output
    assert new_key not in run_result.output
    assert FeedbackStore(cfg.feedback_path, key=new_key).subscriber(101) is not None
    from predoc_pipeline.publish.feedback import StateCorruptError

    with pytest.raises(StateCorruptError):
        FeedbackStore(cfg.feedback_path, key=old_key)


def test_jobicy_status_rotation_does_not_starve_old_records():
    from types import SimpleNamespace
    from urllib.parse import parse_qs, urlsplit

    from predoc_pipeline.ingest.career import _verify_remote_status

    jobs = [{
        "key": f"career:{i}", "jobicy_id": str(i + 100),
        "first_seen_at": "2026-10-01T00:00:00+00:00",
        "availability": "unknown",
    } for i in range(105)]

    class Client:
        def __init__(self):
            self.checked = []

        def get(self, url):
            ids = parse_qs(urlsplit(url).query)["ids"][0].split(",")
            self.checked.append(ids)
            return SimpleNamespace(
                ok=True, status=200, text=json.dumps({
                    "success": True,
                    "jobs": [{"id": int(x), "status": "active"} for x in ids],
                }),
            )

    client = Client()
    _verify_remote_status(client, jobs, [], [], {"fetched": 0})
    _verify_remote_status(client, jobs, [], [], {"fetched": 0})
    assert len(client.checked[0]) == 100
    assert set(client.checked[1][:5]) == {str(i + 100) for i in range(105)} - set(
        client.checked[0]
    )
    assert all("status_checked_at" in job for job in jobs)


def test_valid_jobinja_cards_with_irrelevant_titles_are_healthy_empty(tmp_path):
    from types import SimpleNamespace

    class Client:
        def get(self, url):
            if "jobinja.ir" in url:
                html = '<a href="/companies/example/jobs/q123/accountant">Accountant</a>'
            else:
                html = '<a href="/en/job/accountant/12345">Accountant</a>'
            return SimpleNamespace(ok=True, status=200, text=html, error=None)

    report = tmp_path / "health.json"
    count, errors = poll_career(
        tmp_path / "jobs.ndjson", client=Client(), needs_remote=False,
        needs_iran=True, health_path=report,
    )
    assert count == 0 and errors == []
    sources = json.loads(report.read_text("utf-8"))["sources"]
    assert sources["jobinja"]["status"] == "empty"
    assert sources["irantalent"]["status"] == "empty"


def test_privacy_notice_is_available_in_both_languages():
    from predoc_pipeline.publish.ui import menu

    english, _ = menu(None, "privacy")
    persian, _ = menu({"language": "fa"}, "privacy")
    assert "Fernet-encrypted" in english
    assert "/delete" in english and "historical" in english
    assert "حریم خصوصی" in persian and "/delete" in persian
    home, keyboard = menu(None)
    assert "/privacy" in home
    assert "sub:p:privacy" in str(keyboard)


def test_admin_reconciliation_requires_verified_evidence(tmp_path):
    cfg = settings(tmp_path, "99")
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "predoc")
    assert store.reserve_delivery(101, "academic:pending")
    store.finish_delivery(101, "academic:pending", uncertain=True)
    assert store.reserve_delivery(101, "academic:arrived")
    store.finish_delivery(101, "academic:arrived", uncertain=True)
    store.save()
    api = API([
        message(1, 101, "/reconcile 101 academic:pending absent CONFIRM_NOT_DELIVERED"),
        message(2, 99, "/admin"),
        tap(3, 99, "adm:recovery"),
        message(4, 99, "/reconcile 101 academic:pending absent NOT_VERIFIED"),
        message(5, 99, "/reconcile 101 academic:pending absent CONFIRM_NOT_DELIVERED"),
        message(6, 99, "/reconcile 101 academic:arrived sent 2345"),
        message(7, 101, "/stop"),
        tap(8, 101, "sub:stop:yes"),
    ])
    result = run(cfg, api)
    assert result["failed"] == 0
    assert result["ignored"] >= 1  # A subscriber cannot invoke admin reconciliation.
    assert load_chat_state(cfg.telegram_state_path)["offset"] == 9
    assert any(
        "Private delivery recovery" in body["text"]
        for method, body in api.calls if method == "editMessageText"
    )
    assert any("Verified private delivery outcome" in row["text"] for row in api.sent(99))
    # User-controlled deletion still works after the admin recovery sequence.
    assert FeedbackStore.from_settings(cfg).subscriber(101) is None


def test_admin_reconciliation_does_not_automatically_replay_unknown(tmp_path):
    cfg = settings(tmp_path, "99")
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "predoc")
    assert store.reserve_delivery(101, "academic:unknown")
    store.finish_delivery(101, "academic:unknown", uncertain=True)
    store.save()
    run(cfg, API([
        message(1, 99, "/reconcile 101 academic:unknown absent UNVERIFIED"),
    ]))
    saved = FeedbackStore.from_settings(cfg)
    assert saved.subscriber(101)["deliveries"]["academic:unknown"]["state"] == "uncertain"


def test_admin_action_link_respects_repository_rename(monkeypatch):
    from predoc_pipeline.publish import admin as admin_module

    monkeypatch.setenv("GITHUB_REPOSITORY", "example-org/renamed-collegeum")
    assert admin_module._actions_url().endswith(
        "/example-org/renamed-collegeum/actions/workflows/pipeline.yml"
    )
    monkeypatch.setenv("GITHUB_REPOSITORY", "../hostile")
    assert admin_module._actions_url().startswith(
        "https://github.com/AmirrezaFarnamTaheri/Collegeum/"
    )


def test_provider_probe_separates_empty_match_from_broken_schema():
    from types import SimpleNamespace

    from tools.probe_career_sources import probe_sources

    class Client:
        def get(self, url, **_kwargs):
            if "jobicy.com" in url:
                body = json.dumps({"jobs": [], "success": True})
            elif "jobinja.ir" in url:
                body = '<a href="/companies/example/jobs/1/accountant">Accountant</a>'
            else:
                body = '<a href="/en/job/accountant/12345">Accountant</a>'
            return SimpleNamespace(ok=True, status=200, text=body)

    result = probe_sources(Client())
    assert result["healthy"]
    assert all(
        row["status"] == "healthy_empty"
        for row in result["sources"].values()
    )
    assert all(row["matched"] == 0 for row in result["sources"].values())
