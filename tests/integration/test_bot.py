"""Two-way Telegram: /positions and ✅ ❌ 📝 buttons, against a fake Bot API."""

import json
from pathlib import Path

import httpx
import pytest

from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.urls import url_hash
from predoc_pipeline.publish.bot import build_pages, command_of, select_rows, telegram_sync
from predoc_pipeline.publish.feedback import FeedbackStore, load_state
from predoc_pipeline.publish.keyboards import feedback_row, parse_callback, rebuild
from predoc_pipeline.settings import Settings

OWNER = 42


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_PUBLIC_CHANNEL_ID", "TELEGRAM_ADMIN_CHAT_ID"):
        monkeypatch.delenv(var, raising=False)
    return Settings(
        _env_file=None,
        telegram_bot_token="T",
        telegram_public_channel_id=str(OWNER),
        db_path=str(tmp_path / "predocs.db"),
        state_path=str(tmp_path / "listings.ndjson"),
        feedback_path=str(tmp_path / "feedback.json"),
        telegram_state_path=str(tmp_path / "state.json"),
        dashboard_json=str(tmp_path / "docs" / "listings.json"),
        feed_path=str(tmp_path / "docs" / "feed.xml"),
    )


ROWS = [
    ("Predoc in Macroeconomics", "UPF", "2099-12-20T23:59:59Z", None),
    ("Research Assistant in Finance", "LSE", "2099-10-05T23:59:59Z", None),
    ("Pre-doctoral Fellow", "University of Zurich", None, None),
    ("Old RA", "KU", "2020-09-01T23:59:59Z", None),                    # deadline passed
    ("Filled RA", "SU", "2099-11-01T23:59:59Z", "link no longer works"),  # found filled
]


def add_listings(settings) -> dict[str, str]:
    """Insert published listings; returns title -> url_hash."""
    init(settings.db_path)
    out = {}
    with Database(settings.db_path) as db:
        for i, (title, inst, deadline, closed) in enumerate(ROWS):
            url = f"https://jobs.example.org/{i}"
            lid = db.insert_listing({
                "url_hash": url_hash(url), "apply_url": url, "source_url": url, "source": "t",
                "title": title, "institution": inst, "deadline": deadline, "confidence": 0.9,
                "country": "", "is_remote": 0, "disciplines": "[]", "summary": "",
                "visa_sponsorship_status": "unknown", "language": "en",
                "model_confidence": 0.9, "rule_score": 0.5,
            })
            db.mark_published(lid, 100 + i)
            if closed:
                db.mark_closed(lid, closed)
            out[title] = url_hash(url)
    return out


class FakeTelegram:
    def __init__(self, updates):
        self.updates, self.calls = updates, []

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = str(request.url).rsplit("/", 1)[-1]
        body = json.loads(request.content)
        self.calls.append((method, body))
        if method == "getUpdates":
            off = body.get("offset", 0)
            result = [u for u in self.updates if u["update_id"] >= off]
            return httpx.Response(200, json={"ok": True, "result": result})
        if method == "sendMessage":
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        return httpx.Response(200, json={"ok": True, "result": True})

    def sent(self):
        return [b for m, b in self.calls if m == "sendMessage"]


def msg(uid, text, chat=OWNER):
    return {"update_id": uid, "message": {"message_id": uid, "chat": {"id": chat}, "text": text}}


def tap(uid, data, markup, who=OWNER):
    return {"update_id": uid, "callback_query": {
        "id": f"cb{uid}", "from": {"id": who}, "data": data,
        "message": {"message_id": 900, "chat": {"id": OWNER}, "reply_markup": markup}}}


def run_sync(settings, fake, **kw):
    client = httpx.Client(transport=httpx.MockTransport(fake.handler))
    return telegram_sync(settings, http_client=client, sleep=lambda _s: None, **kw)


def rows_of(settings):
    with Database(settings.db_path) as db:
        return list(db.published_listings())


def test_local_processing_failure_preserves_cursor_and_retries_in_order(settings, monkeypatch):
    import predoc_pipeline.publish.bot as module

    original = module._handle_message
    failed_once = False

    def transient(*args, **kwargs):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise RuntimeError('temporary local processing failure')
        return original(*args, **kwargs)

    monkeypatch.setattr(module, '_handle_message', transient)
    fake = FakeTelegram([msg(77, '/help'), msg(78, '/help')])
    first = run_sync(settings, fake)
    assert first['failed'] == 1 and first['dropped'] == 0 and first['commands'] == 0
    assert load_state(settings.telegram_state_path).get('offset', 0) <= 77
    assert fake.sent() == []
    second = run_sync(settings, fake)
    assert second['commands'] == 2 and second['failed'] == 0
    assert load_state(settings.telegram_state_path)['offset'] == 79
    assert len(fake.sent()) == 2


def test_telegram_server_outage_preserves_update_until_success(settings):
    class OutageTelegram(FakeTelegram):
        unavailable = True
        rejected = 0

        def handler(self, request):
            if self.unavailable and str(request.url).endswith('/sendMessage'):
                self.rejected += 1
                return httpx.Response(503, json={"ok": False, "description": "temporary outage"})
            return super().handler(request)

    fake = OutageTelegram([msg(77, '/help'), msg(78, '/help')])
    first = run_sync(settings, fake)
    assert fake.rejected >= 2  # Exercise retries inside the actual Telegram client.
    assert first['failed'] == 1 and first['commands'] == 0 and first['dropped'] == 0
    assert load_state(settings.telegram_state_path).get('offset', 0) <= 77
    fake.unavailable = False
    second = run_sync(settings, fake)
    assert second['commands'] == 2 and second['failed'] == 0
    assert load_state(settings.telegram_state_path)['offset'] == 79
    assert len(fake.sent()) == 2


def test_callback_replay_after_cursor_failure_preserves_mark(settings, monkeypatch):
    import predoc_pipeline.publish.bot as module

    hashes = add_listings(settings)
    target = hashes['Research Assistant in Finance']
    keyboard = {'inline_keyboard': [feedback_row(target, None, 1)]}
    fake = FakeTelegram([tap(77, f'fb|v|{target[:16]}', keyboard)])
    original = module.save_state
    failed_once = False

    def fail_cursor(path, data):
        nonlocal failed_once
        if data.get('offset') == 78 and not failed_once:
            failed_once = True
            raise OSError('temporary cursor write failure')
        return original(path, data)

    monkeypatch.setattr(module, 'save_state', fail_cursor)
    with pytest.raises(OSError, match='cursor write'):
        run_sync(settings, fake)
    saved = FeedbackStore(settings.feedback_path)
    assert saved.status(target) == 'valid' and saved.callback_seen('cb77')
    assert load_state(settings.telegram_state_path).get('offset', 0) <= 77
    assert not Path(settings.dashboard_json).exists()
    second = run_sync(settings, fake)
    assert second['taps'] == 0
    assert FeedbackStore(settings.feedback_path).status(target) == 'valid'
    assert load_state(settings.telegram_state_path)['offset'] == 78
    assert Path(settings.dashboard_json).exists()


def test_failed_export_retries_without_new_updates(settings, monkeypatch):
    import predoc_pipeline.publish.bot as module

    target = add_listings(settings)['Research Assistant in Finance']
    keyboard = {'inline_keyboard': [feedback_row(target, None, 1)]}
    fake = FakeTelegram([tap(77, f'fb|v|{target[:16]}', keyboard)])
    original = module.state.export_feed
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError('temporary feed write failure')
        return original(*args, **kwargs)

    monkeypatch.setattr(module.state, 'export_feed', fail_once)
    first = run_sync(settings, fake)
    assert first['taps'] == 1 and first['failed'] == 1
    saved = load_state(settings.telegram_state_path)
    assert saved['offset'] == 78 and saved['exports_pending'] is True
    assert FeedbackStore(settings.feedback_path).status(target) == 'valid'
    assert Path(settings.dashboard_json).exists()
    assert not Path(settings.feed_path).exists()

    second = run_sync(settings, fake)
    assert second['received'] == 0 and second['taps'] == 0 and second['failed'] == 0
    assert load_state(settings.telegram_state_path)['exports_pending'] is False
    assert FeedbackStore(settings.feedback_path).status(target) == 'valid'
    assert Path(settings.feed_path).exists()
    run_sync(settings, fake)
    assert attempts == 2


def test_positions_are_sorted_by_deadline_and_paged(settings):
    add_listings(settings)
    store = FeedbackStore(settings.feedback_path)
    chosen = select_rows("positions", rows_of(settings), store)
    # deadline passed and filled ones left out, no deadline last
    assert [r["title"] for r in chosen] == [
        "Research Assistant in Finance", "Predoc in Macroeconomics", "Pre-doctoral Fellow"]
    pages = build_pages("positions", chosen, store, page_size=2)
    assert len(pages) == 2
    assert "3 open positions" in pages[0][0] and "1. Research Assistant in Finance" in pages[0][0]
    assert [b["text"] for b in pages[1][1]["inline_keyboard"][0]] == ["✅ 3", "❌ 3", "📝 3"]
    assert "Tap again to undo" in pages[-1][0]


def test_full_conversation(settings):
    ids = add_listings(settings)
    lse, upf = ids["Research Assistant in Finance"], ids["Predoc in Macroeconomics"]
    kb = {"inline_keyboard": [feedback_row(lse, None, 1), feedback_row(upf, None, 2)]}
    fake = FakeTelegram([
        msg(1, "/positions"),
        msg(2, "/positions", chat=999),                # a stranger: ignored
        tap(3, f"fb|a|{lse[:16]}", kb),               # 📝 applied to LSE
        tap(4, f"fb|x|{upf[:16]}", kb),               # ❌ UPF is not for me
        tap(5, f"fb|v|{upf[:16]}", kb, who=999),      # a stranger's tap: ignored
        msg(6, "/positions"),
        msg(7, "/applied@my_predoc_bot"),
        msg(8, "hello"),
    ])
    summary = run_sync(settings, fake)
    assert summary == {"received": 4, "commands": 4, "taps": 2, "ignored": 2,
                       "failed": 0, "dropped": 0}

    store = FeedbackStore(settings.feedback_path)  # saved to disk
    assert store.status(lse) == "applied" and store.status(upf) == "invalid"
    assert load_state(settings.telegram_state_path)["offset"] == 9

    sent = [b["text"] for b in fake.sent()]
    assert "3 open positions" in sent[0]
    later = "\n".join(sent[1:-2])
    assert "1 open position" in later and "Pre-doctoral Fellow" in later  # applied + hidden gone
    assert any("1 position you applied to" in t and "Research Assistant in Finance" in t
               for t in sent)
    assert "Predoc bot" in sent[-1]                                         # "hello" -> help

    # the tapped message's buttons are redrawn with the choice highlighted
    edits = [b for m, b in fake.calls if m == "editMessageReplyMarkup"]
    last = edits[-1]["reply_markup"]["inline_keyboard"]
    assert last[0][2]["text"] == "• 📝 1" and last[1][1]["text"] == "• ❌ 2"
    # ❌ also takes it off the public dashboard
    dashboard = json.loads(Path(settings.dashboard_json).read_text())
    assert "Predoc in Macroeconomics" not in {r["title"] for r in dashboard["listings"]}


def test_tapping_again_undoes(settings):
    ids = add_listings(settings)
    lse = ids["Research Assistant in Finance"]
    kb = {"inline_keyboard": [feedback_row(lse, None)]}
    run_sync(settings, FakeTelegram([tap(1, f"fb|v|{lse[:16]}", kb)]))
    assert FeedbackStore(settings.feedback_path).status(lse) == "valid"
    run_sync(settings, FakeTelegram([tap(2, f"fb|v|{lse[:16]}", kb)]))
    assert FeedbackStore(settings.feedback_path).status(lse) is None


def test_no_owner_means_no_commands(settings):
    public = settings.model_copy(update={"telegram_public_channel_id": "@mychannel"})
    assert run_sync(public, FakeTelegram([msg(1, "/positions")])) == {
        "received": 0, "commands": 0, "taps": 0, "ignored": 0, "failed": 0, "dropped": 0}


def test_command_words():
    assert command_of("/positions") == "positions"
    assert command_of("Positions please") == "positions"
    assert command_of("/applied@my_bot") == "applied"
    assert command_of("what?") == "help"


def test_rebuild_keeps_link_rows():
    link_row = [{"text": "Apply", "url": "https://x"}]
    kb = {"inline_keyboard": [link_row, feedback_row("a" * 64, None, 4)]}
    out = rebuild(kb, lambda p: "applied")
    assert out["inline_keyboard"][0] == [{"text": "Apply", "url": "https://x"}]
    assert out["inline_keyboard"][1][2]["text"] == "• 📝 4"
    assert parse_callback(out["inline_keyboard"][1][0]["callback_data"]) == ("v", "a" * 16)


def test_broadcast_deduplicates_before_digest(settings):
    from unittest.mock import MagicMock

    from predoc_pipeline.models import Location, PredocListing
    from predoc_pipeline.pipeline import RunStats, _broadcast

    init(settings.db_path)
    with Database(settings.db_path) as db:
        # Pre-seed one published listing
        base_listing = {
            "source": "t",
            "country": "UK",
            "is_remote": 0,
            "disciplines": "[]",
            "summary": "",
            "visa_sponsorship_status": "unknown",
            "language": "en",
            "model_confidence": 0.9,
            "rule_score": 0.5,
            "confidence": 0.9,
        }
        lid1 = db.insert_listing({
            **base_listing,
            "url_hash": url_hash("https://example.org/dup"),
            "apply_url": "https://example.org/dup",
            "source_url": "https://example.org/dup",
            "title": "Existing",
            "institution": "U1",
        })
        db.mark_published(lid1, 999)

        # New listings containing duplicate apply_url and an internal duplicate
        new_lid1 = db.insert_listing({
            **base_listing,
            "url_hash": url_hash("https://example.org/dup?utm=1"),
            "apply_url": "https://example.org/dup?utm=1",
            "source_url": "https://example.org/dup",
            "title": "Dup 1",
            "institution": "U1",
        })
        new_lid2 = db.insert_listing({
            **base_listing,
            "url_hash": url_hash("https://example.org/unique1"),
            "apply_url": "https://example.org/unique1",
            "source_url": "https://example.org/unique1",
            "title": "Unique 1",
            "institution": "U2",
        })

        l1 = PredocListing(
            title="Dup 1",
            institution="U1",
            apply_url="https://example.org/dup?utm=1",
            source_url="https://example.org/dup",
            location=Location(country="UK"),
        )
        l2 = PredocListing(
            title="Unique 1",
            institution="U2",
            apply_url="https://example.org/unique1",
            source_url="https://example.org/unique1",
            location=Location(country="UK"),
        )

        fake_telegram = MagicMock()
        fake_telegram.send_message.return_value = 1001
        stats = RunStats()

        _broadcast([(new_lid1, l1), (new_lid2, l2)], fake_telegram, settings, db, stats)
        # Duplicate should have been marked published without sending to telegram
        assert db.listing(new_lid1)["status"] == "published"
        # Only unique listing sent
        assert fake_telegram.send_message.call_count == 1
        assert stats.published == 1

