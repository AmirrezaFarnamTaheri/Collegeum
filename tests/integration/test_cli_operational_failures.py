"""Credential and inbox completion must reach the process exit status."""

from unittest.mock import patch

from typer.testing import CliRunner

from predoc_pipeline.cli import app
from predoc_pipeline.publish.feedback import generate_key
from predoc_pipeline.settings import Settings


def _run(settings: Settings, summary=None):
    result = {
        "commands": 0,
        "taps": 0,
        "ignored": 0,
        "failed": 0,
        **(summary or {}),
    }
    with (
        patch("predoc_pipeline.cli._settings", return_value=settings),
        patch("predoc_pipeline.publish.bot.telegram_sync", return_value=result) as sync,
    ):
        outcome = CliRunner().invoke(app, ["telegram-sync"])
    return outcome, sync


def test_missing_bot_token_is_not_a_successful_poll():
    cfg = Settings(_env_file=None, telegram_bot_token="",
                   feedback_encryption_key=generate_key())
    result, sync = _run(cfg)
    assert result.exit_code == 1
    assert "TELEGRAM_BOT_TOKEN is required" in result.output
    sync.assert_not_called()


def test_missing_encryption_key_is_not_a_successful_poll():
    cfg = Settings(_env_file=None, telegram_bot_token="offline-token",
                   feedback_encryption_key="")
    result, sync = _run(cfg)
    assert result.exit_code == 1
    assert "FEEDBACK_ENCRYPTION_KEY is required" in result.output
    sync.assert_not_called()


def test_retryable_inbox_error_exits_nonzero_despite_partial_progress():
    cfg = Settings(_env_file=None, telegram_bot_token="offline-token",
                   feedback_encryption_key=generate_key())
    result, sync = _run(cfg, {"commands": 3, "taps": 1, "failed": 1})
    assert sync.call_count == 1
    assert result.exit_code == 1
    assert "3 command(s)" in result.output
    assert "inbox incomplete: 1 deferred operation" in result.output


def test_completed_inbox_stays_successful():
    cfg = Settings(_env_file=None, telegram_bot_token="offline-token",
                   feedback_encryption_key=generate_key())
    result, sync = _run(cfg, {"commands": 2, "taps": 1, "failed": 0})
    assert sync.call_count == 1
    assert result.exit_code == 0
    assert "2 command(s)" in result.output

def test_general_run_never_polls_private_updates_without_explicit_opt_in():
    from types import SimpleNamespace

    fake = SimpleNamespace(
        ingested=0, gated=0, extracted=0, duplicates=0, published=0,
        errors=0, llm_calls=0, outcome="dry-run",
    )
    cfg = Settings(_env_file=None)
    with (
        patch("predoc_pipeline.cli._settings", return_value=cfg),
        patch("predoc_pipeline.pipeline.run", return_value=fake) as mocked,
    ):
        ordinary = CliRunner().invoke(app, ["run", "--dry-run", "--no-private-sync"])
        assert ordinary.exit_code == 0, ordinary.output
        assert mocked.call_args.kwargs["sync_telegram"] is False
        default = CliRunner().invoke(app, ["run", "--dry-run"])
        assert default.exit_code == 0, default.output
        assert mocked.call_args.kwargs["sync_telegram"] is False
        explicitly_enabled = CliRunner().invoke(app, ["run", "--sync-private"])
        assert explicitly_enabled.exit_code == 0, explicitly_enabled.output
        assert mocked.call_args.kwargs["sync_telegram"] is True

