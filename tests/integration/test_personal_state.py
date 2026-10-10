"""Personal-state integrity and privacy (F44, F61, F27, F67)."""

import json
from pathlib import Path

import httpx
import pytest

from predoc_pipeline.publish.feedback import (
    FeedbackStore,
    StateCorruptError,
    encrypted_path,
    generate_key,
    load_chat_state,
)
from predoc_pipeline.publish.keyboards import feedback_row

from .test_bot import (  # noqa: F401,F811 - pytest fixtures re-exported
    FakeTelegram,
    add_listings,
    msg,
    run_sync,
    settings,  # noqa: F811
    tap,
)


def corrupt_siblings(path: Path) -> list[Path]:
    return list(path.parent.glob(path.name + ".corrupt-*"))


# --- F44: corrupt state never becomes an empty state -------------------------


@pytest.mark.parametrize("content", ['{"marks": {"a": ', "[]", '{"marks": null}',
                                     '{"marks": {"h": "applied"}}',
                                     '{"marks": {"h": {"status": "bogus"}}}',
                                     '{"marks": {}, "callbacks": [1]}', ""])
def test_corrupt_feedback_is_preserved_and_raises(tmp_path, content):
    path = tmp_path / "feedback.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(StateCorruptError):
        FeedbackStore(path)
    assert path.read_text(encoding="utf-8") == content  # untouched
    copies = corrupt_siblings(path)
    assert len(copies) == 1 and copies[0].read_text(encoding="utf-8") == content


def test_absent_feedback_is_empty_and_valid_roundtrips(tmp_path):
    path = tmp_path / "feedback.json"
    store = FeedbackStore(path)
    assert store.marks == {}
    store.set("h1", "applied", title="T")
    store.save()
    assert FeedbackStore(path).status("h1") == "applied"


@pytest.mark.parametrize("plaintext_twin", [False, True])
def test_encrypted_feedback_requires_original_key_even_with_plaintext_twin(
    tmp_path, plaintext_twin,
):
    path = tmp_path / "feedback.json"
    key = generate_key()
    store = FeedbackStore(path, key=key)
    store.set("h1", "applied", title="Saved application")
    store.save()
    encrypted = encrypted_path(path).read_bytes()
    if plaintext_twin:
        path.write_text('{"marks": {}}', encoding="utf-8")
    with pytest.raises(StateCorruptError, match="FEEDBACK_ENCRYPTION_KEY"):
        FeedbackStore(path)
    assert encrypted_path(path).read_bytes() == encrypted
    assert FeedbackStore(path, key=key).status("h1") == "applied"


@pytest.mark.parametrize("content", ['{"offset": "7"}', '{"offset": -1}', '{"offset": true}',
                                     '{"offset": ', "[]"])
def test_corrupt_cursor_is_not_reset(tmp_path, content):
    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(StateCorruptError):
        load_chat_state(path)
    assert path.read_text(encoding="utf-8") == content


def test_sync_stops_on_corrupt_state_without_touching_it(settings):
    add_listings(settings)
    Path(settings.telegram_state_path).write_text('{"offset": ', encoding="utf-8")
    fake = FakeTelegram([msg(1, "/positions")])
    with pytest.raises(StateCorruptError):
        run_sync(settings, fake)
    assert Path(settings.telegram_state_path).read_text(encoding="utf-8") == '{"offset": '
    assert fake.calls == []  # nothing was fetched, so nothing could be lost


# --- F61: a replayed callback cannot undo a saved mark ------------------------


def test_replayed_callback_does_not_toggle_mark(settings):
    ids = add_listings(settings)
    lse = ids["Research Assistant in Finance"]
    kb = {"inline_keyboard": [feedback_row(lse, None, 1)]}
    update = tap(5, f"fb|a|{lse[:16]}", kb)
    run_sync(settings, FakeTelegram([update]))
    assert FeedbackStore(settings.feedback_path).status(lse) == "applied"
    # Cursor lost / batch redelivered: the very same callback arrives again.
    Path(settings.telegram_state_path).unlink()
    summary = run_sync(settings, FakeTelegram([update]))
    assert FeedbackStore(settings.feedback_path).status(lse) == "applied"
    assert summary["taps"] == 0
    # A genuinely new tap still undoes it.
    run_sync(settings, FakeTelegram([tap(6, f"fb|a|{lse[:16]}", kb)]))
    assert FeedbackStore(settings.feedback_path).status(lse) is None


# --- F27: transient outages do not acknowledge updates ------------------------


class OutageTelegram(FakeTelegram):
    def __init__(self, updates, fail_sends):
        super().__init__(updates)
        self.fail_sends = fail_sends

    def handler(self, request):
        method = str(request.url).rsplit("/", 1)[-1]
        if method == "sendMessage" and self.fail_sends:
            self.calls.append((method, json.loads(request.content)))
            return httpx.Response(503, json={"ok": False, "description": "unavailable"})
        return super().handler(request)


def test_transient_failure_keeps_update_pending_then_retries(settings):
    add_listings(settings)
    down = OutageTelegram([msg(77, "/positions")], fail_sends=True)
    summary = run_sync(settings, down)
    assert summary["failed"] == 1 and summary["commands"] == 0 and summary["received"] == 1
    state = json.loads(Path(settings.telegram_state_path).read_text())
    assert "offset" not in state or state["offset"] <= 77  # update 77 not acknowledged
    up = OutageTelegram([msg(77, "/positions")], fail_sends=False)
    summary = run_sync(settings, up)
    assert summary["commands"] == 1 and summary["failed"] == 0
    assert up.sent()
    assert json.loads(Path(settings.telegram_state_path).read_text())["offset"] == 78


def test_outage_does_not_skip_later_updates_or_reapply_earlier_taps(settings):
    ids = add_listings(settings)
    lse = ids["Research Assistant in Finance"]
    kb = {"inline_keyboard": [feedback_row(lse, None, 1)]}
    updates = [tap(1, f"fb|v|{lse[:16]}", kb), msg(2, "/positions"),
               tap(3, f"fb|a|{lse[:16]}", kb)]
    run_sync(settings, OutageTelegram(updates, fail_sends=True))
    store = FeedbackStore(settings.feedback_path)
    assert store.status(lse) == "valid"  # tap 1 applied, tap 3 not yet reached
    assert json.loads(Path(settings.telegram_state_path).read_text())["offset"] == 2
    run_sync(settings, OutageTelegram(updates, fail_sends=False))
    assert FeedbackStore(settings.feedback_path).status(lse) == "applied"  # no double toggle


def test_permanent_rejection_is_dropped_not_retried_forever(settings):
    add_listings(settings)

    class Rejecting(FakeTelegram):
        def handler(self, request):
            if str(request.url).endswith("sendMessage"):
                return httpx.Response(400, json={"ok": False, "description": "bad entities"})
            return super().handler(request)

    summary = run_sync(settings, Rejecting([msg(9, "/positions")]))
    assert summary["dropped"] == 1 and summary["failed"] == 0
    assert json.loads(Path(settings.telegram_state_path).read_text())["offset"] == 10


# --- F67: marks are not stored in plaintext when a key is configured ----------


def test_marks_are_encrypted_at_rest(tmp_path):
    key = generate_key()
    path = tmp_path / "feedback.json"
    store = FeedbackStore(path, key=key)
    store.set("a" * 64, "applied", title="Secret Predoc Title", institution="Private Univ")
    store.save()
    enc = encrypted_path(path)
    assert enc.exists() and not path.exists()
    blob = enc.read_bytes()
    assert b"Secret Predoc" not in blob and b"applied" not in blob
    assert FeedbackStore(path, key=key).status("a" * 64) == "applied"


def test_wrong_key_is_an_error_not_an_empty_store(tmp_path):
    path = tmp_path / "feedback.json"
    store = FeedbackStore(path, key=generate_key())
    store.set("h", "valid")
    store.save()
    before = encrypted_path(path).read_bytes()
    with pytest.raises(StateCorruptError):
        FeedbackStore(path, key=generate_key())
    assert encrypted_path(path).read_bytes() == before


def test_plaintext_marks_migrate_and_plaintext_is_removed(tmp_path):
    path = tmp_path / "feedback.json"
    plain = FeedbackStore(path)
    plain.set("h", "applied", title="T")
    plain.save()
    assert path.exists()
    key = generate_key()
    migrated = FeedbackStore(path, key=key)
    assert migrated.status("h") == "applied"
    migrated.save()
    assert not path.exists() and encrypted_path(path).exists()
    assert FeedbackStore(path, key=key).status("h") == "applied"


def test_invalid_key_message_is_actionable(tmp_path):
    with pytest.raises(ValueError, match="FEEDBACK_ENCRYPTION_KEY"):
        FeedbackStore(tmp_path / "f.json", key="not-a-key")


def test_sync_persists_encrypted_marks_only(settings):
    key = generate_key()
    settings = settings.model_copy(update={"feedback_encryption_key": key})
    ids = add_listings(settings)
    lse = ids["Research Assistant in Finance"]
    kb = {"inline_keyboard": [feedback_row(lse, None, 1)]}
    run_sync(settings, FakeTelegram([tap(1, f"fb|a|{lse[:16]}", kb)]))
    assert not Path(settings.feedback_path).exists()
    assert encrypted_path(settings.feedback_path).exists()
    assert FeedbackStore.from_settings(settings).status(lse) == "applied"


def test_workflows_commit_only_the_encrypted_file():
    root = Path(__file__).resolve().parents[2]
    for name in ("pipeline.yml", "telegram.yml"):
        text = (root / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "data/feedback.json" not in text and "data/feedback.enc" in text
        assert "FEEDBACK_ENCRYPTION_KEY" in text
    assert "data/feedback.json" in (root / ".gitignore").read_text(encoding="utf-8")
