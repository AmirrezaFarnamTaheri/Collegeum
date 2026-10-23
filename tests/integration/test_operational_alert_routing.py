"""Operational failure messages must never reach ordinary bot recipients."""
from __future__ import annotations

from unittest.mock import patch

from predoc_pipeline.alerts import notify_admin
from predoc_pipeline.settings import Settings


def configured(**overrides):
    return Settings(_env_file=None, **{
        "telegram_bot_token": "offline-token",
        "telegram_public_channel_id": "12345",
        **overrides,
    })


def test_operational_alerts_are_disabled_by_default_even_with_admin_credentials():
    settings = configured(telegram_admin_chat_id="99999")
    with patch("predoc_pipeline.alerts.TelegramClient") as sender:
        notify_admin(settings, "technical traceback secret=do-not-send")
    sender.assert_not_called()


def test_public_private_destination_never_receives_admin_alerts():
    settings = configured(telegram_operational_alerts_enabled=True)
    assert settings.alert_chat_id == ""
    with patch("predoc_pipeline.alerts.TelegramClient") as sender:
        notify_admin(settings, "source health debug data")
    sender.assert_not_called()


def test_same_public_and_admin_chat_never_receives_operational_alerts():
    settings = configured(
        telegram_operational_alerts_enabled=True,
        telegram_admin_chat_id="12345",
    )
    assert settings.alert_chat_id == ""
    with patch("predoc_pipeline.alerts.TelegramClient") as sender:
        notify_admin(settings, "sensitive diagnostic information")
    sender.assert_not_called()


def test_explicit_opt_in_sends_maintenance_alert_only_to_distinct_private_admin():
    settings = configured(
        telegram_operational_alerts_enabled=True,
        telegram_admin_chat_id="99999",
    )
    assert settings.alert_chat_id == "99999"
    with patch("predoc_pipeline.alerts.TelegramClient") as sender:
        notify_admin(settings, "Source check requires maintenance")
    sender.assert_called_once()
    sent = sender.return_value.__enter__.return_value.send_plain.call_args
    assert sent.kwargs["chat_id"] == "99999"


def test_negative_channel_id_is_not_a_valid_operational_admin_recipient():
    settings = configured(
        telegram_operational_alerts_enabled=True,
        telegram_admin_chat_id="-10012345678",
    )
    assert settings.alert_chat_id == ""
    with patch("predoc_pipeline.alerts.TelegramClient") as sender:
        notify_admin(settings, "debug log")
    sender.assert_not_called()


def test_disabled_operational_alerts_do_not_fail_a_run(monkeypatch):
    from predoc_pipeline.pipeline import RunStats, _maybe_alert

    class EmptyRunDatabase:
        def consecutive_empty_runs(self):
            return 0

        def source_failure_streaks(self):
            return {}

    settings = configured(empty_run_alert_threshold=1)
    stats = RunStats()
    monkeypatch.setattr("predoc_pipeline.alerts.notify_admin", lambda *_: False)

    _maybe_alert(EmptyRunDatabase(), settings, stats, {})

    assert stats.errors == 0


def test_enabled_but_undelivered_operational_alert_fails_a_run(monkeypatch):
    from predoc_pipeline.pipeline import RunStats, _maybe_alert

    class EmptyRunDatabase:
        def consecutive_empty_runs(self):
            return 0

        def source_failure_streaks(self):
            return {}

    settings = configured(
        telegram_operational_alerts_enabled=True,
        telegram_admin_chat_id="99999",
        empty_run_alert_threshold=1,
    )
    stats = RunStats()
    monkeypatch.setattr("predoc_pipeline.alerts.notify_admin", lambda *_: False)

    _maybe_alert(EmptyRunDatabase(), settings, stats, {})

    assert stats.errors == 1
