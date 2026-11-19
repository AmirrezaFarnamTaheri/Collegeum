"""Runner restarts must not result in a second Telegram send for one official call."""
from __future__ import annotations

import base64
import json
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from predoc_pipeline.publish.admissions import publish_official_admissions
from predoc_pipeline.publish.official_calls import official_calls_health, publish_official_calls
from predoc_pipeline.publish.telegram import TelegramError
from predoc_pipeline.publish.telegram_intents import GitHubIntentReserver

NOW = datetime(2026, 11, 20, 8, tzinfo=UTC)
URL = "https://ieb.ub.edu/en/phd-scholarship-in-economics-2027/"
DE_URL = "https://berlinschoolofeconomics.de/phd-program/application"

CALL = {
    "source_id": "ieb", "institution": "Barcelona Institute of Economics (IEB)",
    "country_code": "ES", "official_url": URL, "title": "PhD Scholarship in Economics 2027",
    "status": "verified", "kind": "phd_scholarship", "intake_year": 2027,
    "deadline_iso": "2026-12-11", "deadline_kind": "scholarship",
    "evidence_url": URL, "evidence_excerpt": (
        "Interested candidates must complete both steps by 11 December 2026"
    ), "location_evidence_url": URL,
    "location_evidence": "ES: official postal address 08034 Barcelona and telephone +34",
    "checked_at": "2026-11-20T07:00:00Z",
}
ADMISSIONS = {
    "kind": "economics_phd_admissions_observations",
    "scope": "official_programme_sources_only",
    "source": {"deadline_values_reused": False},
    "programmes": [{
        "institution": "Berlin School of Economics", "country_code": "DE",
        "official_programme_url": DE_URL, "evidence_url": DE_URL,
        "status": "verified", "checked_at": "2026-11-20T07:00:00Z",
        "deadline_iso": "2027-01-15",
        "evidence_excerpt": "Economics PhD application deadline: 2027-01-15.",
    }],
}


def _calls():
    return {"kind": "official_phd_call_observations", "version": 1, "calls": [CALL]}


def test_github_reservation_uses_atomic_create_only_no_ledger_overwrite():
    reserver = GitHubIntentReserver(
        repository="AmirrezaFarnamTaheri/Collegeum",
        token="never-log-this-test-token",
    )
    reply = Mock()
    reply.status = 201
    reply.__enter__ = Mock(return_value=reply)
    reply.__exit__ = Mock(return_value=None)
    with patch("urllib.request.urlopen", return_value=reply) as transport:
        reserver.reserve("calls", "a" * 32, "initial")

    request = transport.call_args.args[0]
    assert request.get_method() == "PUT"
    assert request.full_url.startswith(
        "https://api.github.com/repos/AmirrezaFarnamTaheri/Collegeum/"
        "contents/data/telegram_delivery_intents/calls/" + "a" * 32
    )
    payload = json.loads(request.data)
    assert payload["branch"] == "main"
    assert payload["message"].endswith("[skip ci]")
    assert "sha" not in payload  # Existing reservation must not be overwritten.
    reserved = json.loads(base64.b64decode(payload["content"]))
    assert reserved["namespace"] == "calls"
    assert reserved["opportunity_key"] == "a" * 32
    assert "never-log-this-test-token" not in request.full_url
    assert "never-log-this-test-token" not in str(payload)


def test_duplicate_422_or_failed_github_write_is_fail_closed():
    reserver = GitHubIntentReserver(repository="Owner/Repo", token="secret-abc")
    for error in (
        urllib.error.HTTPError("https://api.github.com", 422, "conflict", None, None),
        urllib.error.HTTPError("https://api.github.com", 403, "denied", None, None),
        urllib.error.URLError("connection interrupted"),
    ):
        with patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(OSError) as failed:
                reserver.reserve("admissions", "a" * 32, "initial")
            assert "secret-abc" not in str(failed.value)


def test_invalid_namespace_repository_and_opportunity_key_cannot_send_network():
    for repo in ("", "owner/repo/extra", "evil.net/path", "owner/ repo"):
        with pytest.raises(ValueError):
            GitHubIntentReserver(repository=repo, token="token")
    store = GitHubIntentReserver(repository="Owner/Repo", token="token")
    with patch("urllib.request.urlopen") as transport:
        for namespace, key in (("vacancies", "a" * 32), ("calls", "../../bad")):
            with pytest.raises(ValueError):
                store.reserve(namespace, key, "initial")
        transport.assert_not_called()


def test_call_reservation_happens_before_telegram_send(tmp_path: Path):
    catalog = tmp_path / "calls.json"
    ledger = tmp_path / "ledger.json"
    catalog.write_text(json.dumps(_calls()), encoding="utf-8")
    sequence: list[str] = []
    def reserve(namespace, key, operation):
        assert namespace == "calls" and len(key) == 32 and operation == "initial"
        sequence.append("durable")
        assert json.loads(ledger.read_text())["deliveries"][key]["state"] == "pending"

    telegram = Mock()
    telegram.send_message.side_effect = lambda **kwargs: (
        sequence.append("telegram") or 901
    )
    assert publish_official_calls(catalog, ledger, telegram, chat_id="@channel",
                                  enabled=True, now=NOW, reserve_intent=reserve) == 1
    assert sequence == ["durable", "telegram"]
    assert publish_official_calls(catalog, ledger, telegram, chat_id="@channel",
                                  enabled=True, now=NOW, reserve_intent=reserve) == 0


def test_failed_remote_reservation_aborts_call_before_telegram(tmp_path: Path):
    catalog = tmp_path / "calls.json"
    ledger = tmp_path / "ledger.json"
    catalog.write_text(json.dumps(_calls()), encoding="utf-8")
    telegram = Mock()
    def fail(*args):
        raise OSError("github durable reservation not recorded")

    with pytest.raises(OSError):
        publish_official_calls(catalog, ledger, telegram, chat_id="@channel",
                               enabled=True, now=NOW, reserve_intent=fail)
    telegram.send_message.assert_not_called()
    assert next(iter(json.loads(ledger.read_text())["deliveries"].values()))[
        "state"] == "pending"


def test_admissions_reservation_before_send_and_fails_closed(tmp_path: Path):
    catalog = tmp_path / "admissions.json"
    ledger = tmp_path / "receipts.json"
    catalog.write_text(json.dumps(ADMISSIONS), encoding="utf-8")
    sequence = []
    telegram = Mock()
    telegram.send_message.side_effect = lambda **kwargs: (
        sequence.append("telegram") or 902
    )
    def reserve(namespace, key, operation):
        assert namespace == "admissions"
        assert operation == "initial" and len(key) == 32
        sequence.append("durable")
        assert next(iter(json.loads(ledger.read_text())["deliveries"].values()))[
            "state"] == "pending"
    assert publish_official_admissions(catalog, ledger, telegram, chat_id="@channel",
                                       enabled=True, now=NOW, reserve_intent=reserve) == 1
    assert sequence == ["durable", "telegram"]


def test_admissions_reissue_gets_new_reservation_identity(tmp_path: Path):
    from predoc_pipeline.publish.admissions import _delivery_key

    catalog = tmp_path / "admissions.json"
    ledger = tmp_path / "receipts.json"
    row = ADMISSIONS["programmes"][0]
    catalog.write_text(json.dumps(ADMISSIONS), encoding="utf-8")
    key = _delivery_key(row)
    ledger.write_text(json.dumps({"version": 1, "deliveries": {
        key: {"state": "reissue_authorized", "prior_message_id": 778,
              "message_id": 778, "reissue_authorized_at": "2026-11-20T07:30:00Z",
              "institution": row["institution"], "country_code": "DE"}
    }}), encoding="utf-8")
    telegram = Mock()
    telegram.send_message.return_value = 903
    calls = []
    def reserve(namespace, ident, operation):
        calls.append((namespace, ident, operation))
    assert publish_official_admissions(
        catalog, ledger, telegram, chat_id="@channel",
        enabled=True, now=NOW, reserve_intent=reserve,
    ) == 1
    assert calls == [
        ("admissions", key, "reissue:778:2026-11-20T07:30:00Z")
    ]


def test_production_workflow_enables_reservations_not_only_telegram_publishing():
    workflow = Path(".github/workflows/pipeline.yml").read_text(encoding="utf-8")
    settings = Path("src/predoc_pipeline/settings.py").read_text(encoding="utf-8")
    assert "TELEGRAM_GIT_DURABLE_INTENTS_ENABLED: 'true'" in workflow
    assert "GITHUB_TOKEN: ${{ github.token }}" in workflow
    assert "telegram_git_durable_intents_enabled: bool = False" in settings
    assert "github.ref == 'refs/heads/main'" in workflow



def test_runner_crash_after_telegram_accepts_cannot_resend_with_fresh_ledger(
    tmp_path: Path,
):
    """The remote create-only intent survives even if the local receipt vanishes."""
    catalog = tmp_path / "calls.json"
    ledger = tmp_path / "ledger.json"
    catalog.write_text(json.dumps(_calls()), encoding="utf-8")
    telegram = Mock()
    telegram.send_message.side_effect = RuntimeError("runner died after Telegram request")
    store = GitHubIntentReserver(repository="Owner/Repo", token="test-token")
    first = Mock()
    first.status = 201
    first.__enter__ = Mock(return_value=first)
    first.__exit__ = Mock(return_value=None)
    already_reserved = urllib.error.HTTPError(
        "https://api.github.com", 422, "reservation exists", None, None,
    )
    with patch("urllib.request.urlopen", side_effect=[first, already_reserved]):
        with pytest.raises(RuntimeError, match="runner died"):
            publish_official_calls(
                catalog, ledger, telegram, chat_id="@channel",
                enabled=True, now=NOW, reserve_intent=store.reserve,
            )
        # Simulate loss of the ephemeral runner's local pending checkpoint.
        ledger.unlink()
        telegram.send_message.side_effect = None
        telegram.send_message.return_value = 916
        with pytest.raises(OSError, match="reservation"):
            publish_official_calls(
                catalog, ledger, telegram, chat_id="@channel",
                enabled=True, now=NOW, reserve_intent=store.reserve,
            )
    assert telegram.send_message.call_count == 1


def test_production_main_fails_closed_if_intent_store_unavailable(tmp_path: Path):
    catalog = tmp_path / "calls.json"
    ledger = tmp_path / "ledger.json"
    catalog.write_text(json.dumps(_calls()), encoding="utf-8")
    telegram = Mock()
    with patch.dict("os.environ", {
        "GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW": "predoc-pipeline",
    }):
        with pytest.raises(OSError, match="durable"):
            publish_official_calls(
                catalog, ledger, telegram, chat_id="@channel", enabled=True, now=NOW,
            )
        with pytest.raises(OSError, match="durable"):
            admissions = tmp_path / "adm.json"
            admissions.write_text(json.dumps(ADMISSIONS), encoding="utf-8")
            publish_official_admissions(
                admissions, tmp_path / "adm_receipts.json", telegram,
                chat_id="@channel", enabled=True, now=NOW,
            )
    telegram.send_message.assert_not_called()


def test_truly_new_admissions_cycle_uses_distinct_reservation_operation(tmp_path: Path):
    from predoc_pipeline.publish.admissions import _delivery_key

    catalog = tmp_path / "adm.json"
    ledger = tmp_path / "receipts.json"
    row = ADMISSIONS["programmes"][0]
    key = _delivery_key(row)
    catalog.write_text(json.dumps(ADMISSIONS), encoding="utf-8")
    ledger.write_text(json.dumps({"version": 1, "deliveries": {
        key: {
            "state": "confirmed", "message_id": 609,
            "sent_at": "2026-01-01T00:00:00Z",
            "deadline_iso": "2026-03-01",
            "institution": row["institution"], "country_code": "DE",
        }
    }}), encoding="utf-8")
    telegram = Mock()
    telegram.send_message.return_value = 917
    markers = []
    assert publish_official_admissions(
        catalog, ledger, telegram, chat_id="@channel", enabled=True, now=NOW,
        reserve_intent=lambda ns, key, operation: markers.append(operation),
    ) == 1
    assert markers == ["cycle:2027-01-15"]



def test_unconfirmed_durable_intent_remains_visible_as_undelivered(tmp_path: Path):
    import hashlib

    catalog = tmp_path / "calls.json"
    ledger = tmp_path / "ledger.json"
    catalog.write_text(json.dumps(_calls()), encoding="utf-8")
    from predoc_pipeline.publish.official_calls import call_key

    key = call_key(CALL)
    ledger.write_text(json.dumps({"version": 1, "deliveries": {
        key: {"state": "pending", "attempted_at": "2026-11-20T07:35:00Z",
              "official_url": URL},
    }}), encoding="utf-8")
    health = official_calls_health(catalog, ledger, now=NOW)
    assert health["pending"] == 1
    assert health["unpublished"] == 1
    assert health["confirmed"] == 0
    assert health["status"] == "degraded"


def test_definite_telegram_rejection_retains_durable_intent_for_review(
    tmp_path: Path,
):
    """A reserved operation cannot auto-retry even if Telegram replied 429."""
    catalog = tmp_path / "calls.json"
    ledger = tmp_path / "ledger.json"
    catalog.write_text(json.dumps(_calls()), encoding="utf-8")
    telegram = Mock()
    telegram.send_message.side_effect = TelegramError("rate limited", status=429)
    accepted_reservations = []
    assert publish_official_calls(
        catalog, ledger, telegram, chat_id="@channel",
        enabled=True, now=NOW,
        reserve_intent=lambda ns, key, op: accepted_reservations.append(op),
    ) == 0
    state = next(iter(json.loads(ledger.read_text())["deliveries"].values()))
    assert state["state"] == "retry_held"
    assert accepted_reservations == ["initial"]
    telegram.send_message.side_effect = None
    assert publish_official_calls(
        catalog, ledger, telegram, chat_id="@channel",
        enabled=True, now=NOW,
        reserve_intent=lambda ns, key, op: accepted_reservations.append(op),
    ) == 0
    telegram.send_message.assert_called_once()
