"""Pre-send immutable intents AND post-send durable outcomes for official calls."""
from __future__ import annotations

import base64
import json
import urllib.error
from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest

from predoc_pipeline.publish.admissions import publish_official_admissions
from predoc_pipeline.publish.official_calls import (
    call_key,
    publish_official_calls,
)
from predoc_pipeline.publish.telegram import TelegramError
from predoc_pipeline.publish.telegram_intents import GitHubIntentReserver

NOW = datetime(2026, 11, 20, 8, tzinfo=UTC)
URL = "https://ieb.ub.edu/en/phd-scholarship-in-economics-2027/"
ROW = {
    "source_id": "ieb", "institution": "Barcelona Institute of Economics (IEB)",
    "country_code": "ES", "official_url": URL, "title": "PhD Scholarship in Economics 2027",
    "status": "verified", "kind": "phd_scholarship", "intake_year": 2027,
    "deadline_iso": "2026-12-11", "deadline_kind": "scholarship",
    "evidence_url": URL,
    "evidence_excerpt": "Interested candidates must complete both steps by 11 December 2026",
    "location_evidence_url": URL,
    "location_evidence": "ES: official postal address 08034 Barcelona and telephone +34",
    "checked_at": "2026-11-20T07:00:00Z",
}
ADMISSION_URL = "https://berlinschoolofeconomics.de/phd-program/application"
ADMISSIONS = {
    "kind": "economics_phd_admissions_observations",
    "scope": "official_programme_sources_only",
    "source": {"deadline_values_reused": False},
    "programmes": [{
        "institution": "Berlin School of Economics", "country_code": "DE",
        "official_programme_url": ADMISSION_URL, "evidence_url": ADMISSION_URL,
        "status": "verified", "checked_at": "2026-11-20T07:00:00Z",
        "deadline_iso": "2027-01-15",
        "evidence_excerpt": "Economics PhD application deadline: 2027-01-15.",
    }],
}


def _catalog(tmp_path, *rows):
    path = tmp_path / "official_calls.json"
    path.write_text(json.dumps({
        "version": 1, "kind": "official_phd_call_observations", "calls": list(rows),
    }), encoding="utf-8")
    return path


def test_durable_outcome_create_only_never_overwrites_intent_or_exposes_token():
    store = GitHubIntentReserver(repository="Owner/Repo", token="private-token")
    reply = Mock(status=201)
    reply.__enter__ = Mock(return_value=reply)
    reply.__exit__ = Mock(return_value=None)
    with patch("urllib.request.urlopen", return_value=reply) as transport:
        store.record_outcome("calls", "a" * 32, "initial", "confirmed", message_id=716)
    request = transport.call_args.args[0]
    assert request.get_method() == "PUT"
    assert "/contents/data/telegram_delivery_outcomes/calls/" in request.full_url
    payload = json.loads(request.data)
    assert payload["branch"] == "main"
    assert "sha" not in payload
    assert payload["message"].endswith("[skip ci]")
    document = json.loads(base64.b64decode(payload["content"]))
    assert document["state"] == "confirmed"
    assert document["message_id"] == 716
    assert document["namespace"] == "calls"
    assert document["opportunity_key"] == "a" * 32
    assert document["operation_hash"]
    assert "private-token" not in str(payload)


def test_durable_outcome_rejects_invalid_state_and_noninteger_message_id():
    store = GitHubIntentReserver(repository="Owner/Repo", token="secret")
    with patch("urllib.request.urlopen") as transport:
        for state, message_id in [
            ("confirmed", True), ("confirmed", 0), ("confirmed", None),
            ("retry", None), ("uncertain", 404),
        ]:
            with pytest.raises(ValueError):
                store.record_outcome("calls", "a" * 32, "initial", state,
                                     message_id=message_id)
        transport.assert_not_called()


def test_durable_outcome_write_failure_is_not_claimed_as_confirmed():
    store = GitHubIntentReserver(repository="Owner/Repo", token="secret")
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
        "https://api.github.com", 409, "concurrent commit", None, None,
    )):
        with pytest.raises(OSError, match="outcome"):
            store.record_outcome("admissions", "a" * 32, "initial",
                                 "confirmed", message_id=716)


def test_official_call_checkpoint_and_remote_outcome_after_confirmed_send(tmp_path):
    catalog = _catalog(tmp_path, ROW)
    ledger = tmp_path / "ledger.json"
    trace = []
    telegram = Mock()

    def send_message(**kwargs):
        assert trace == ["reserved"]
        trace.append("sent")
        return 777

    def persist(namespace, key, operation, state, message_id):
        assert trace == ["reserved", "sent"]
        assert (namespace, key, operation, state, message_id) == (
            "calls", call_key(ROW), "initial", "confirmed", 777,
        )
        assert json.loads(ledger.read_text())["deliveries"][key]["state"] == "confirmed"
        trace.append("outcome")

    telegram.send_message.side_effect = send_message
    assert publish_official_calls(
        catalog, ledger, telegram, chat_id="@channel", enabled=True, now=NOW,
        reserve_intent=lambda *args: trace.append("reserved"),
        record_outcome=persist,
    ) == 1
    assert trace == ["reserved", "sent", "outcome"]
    assert telegram.send_message.call_count == 1


def test_failed_durable_outcome_does_not_erase_local_confirmed_receipt(tmp_path):
    catalog = _catalog(tmp_path, ROW)
    ledger = tmp_path / "ledger.json"
    telegram = Mock()
    telegram.send_message.return_value = 778

    def unavailable(*args):
        raise OSError("remote outcome not persisted")

    with pytest.raises(OSError, match="outcome"):
        publish_official_calls(
            catalog, ledger, telegram, chat_id="@channel", enabled=True, now=NOW,
            reserve_intent=Mock(), record_outcome=unavailable,
        )
    assert json.loads(ledger.read_text())["deliveries"][call_key(ROW)] == {
        **json.loads(ledger.read_text())["deliveries"][call_key(ROW)]
    }
    assert json.loads(ledger.read_text())["deliveries"][call_key(ROW)]["message_id"] == 778
    assert publish_official_calls(
        catalog, ledger, telegram, chat_id="@channel", enabled=True, now=NOW,
        reserve_intent=Mock(), record_outcome=unavailable,
    ) == 0
    telegram.send_message.assert_called_once()


def test_uncertain_telegram_response_persists_remote_uncertain_outcome(tmp_path):
    catalog = _catalog(tmp_path, ROW)
    ledger = tmp_path / "ledger.json"
    telegram = Mock()
    telegram.send_message.side_effect = TelegramError("response lost", uncertain=True)
    outcomes = []
    assert publish_official_calls(
        catalog, ledger, telegram, chat_id="@channel", enabled=True, now=NOW,
        reserve_intent=Mock(), record_outcome=lambda *args: outcomes.append(args),
    ) == 0
    assert outcomes == [("calls", call_key(ROW), "initial", "uncertain", None)]
    assert json.loads(ledger.read_text())["deliveries"][call_key(ROW)]["state"] == "uncertain"


def test_admissions_confirmation_has_durable_outcome_and_correct_operation(tmp_path):
    catalog = tmp_path / "admissions.json"
    ledger = tmp_path / "ledger.json"
    catalog.write_text(json.dumps(ADMISSIONS), encoding="utf-8")
    telegram = Mock()
    telegram.send_message.return_value = 779
    observed = []
    assert publish_official_admissions(
        catalog, ledger, telegram, chat_id="@channel", enabled=True, now=NOW,
        reserve_intent=lambda *args: observed.append(("reserve", args)),
        record_outcome=lambda *args: observed.append(("outcome", args)),
    ) == 1
    assert len(observed) == 2
    assert observed[0][0] == "reserve"
    assert observed[1][0] == "outcome"
    assert observed[1][1] == (*observed[0][1], "confirmed", 779)


def test_production_main_requires_remote_outcome_callback_for_official_sends(tmp_path):
    catalog = _catalog(tmp_path, ROW)
    ledger = tmp_path / "ledger.json"
    telegram = Mock()
    telegram.send_message.return_value = 790
    with patch.dict("os.environ", {
        "GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW": "predoc-pipeline",
    }):
        with pytest.raises(OSError, match="outcome"):
            publish_official_calls(
                catalog, ledger, telegram, chat_id="@channel", enabled=True,
                now=NOW, reserve_intent=Mock(),
            )
    telegram.send_message.assert_not_called()
