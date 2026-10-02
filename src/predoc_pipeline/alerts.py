"""Maintainer alerts.

Deliberately minimal: one function, one channel (a Telegram message to the
admin chat, configured separately from the public channel), with a stderr
fallback so an alert is never silently dropped just because the admin chat is
not set up yet. This is what turns "the workflow is green but nothing has
posted in a week" into something that actually reaches a person.
"""

from __future__ import annotations

from .logging_setup import get_logger
from .publish.telegram import TelegramClient, TelegramError
from .settings import Settings

log = get_logger(__name__)

__all__ = ["notify_admin"]


def notify_admin(settings: Settings, message: str) -> None:
    """Best-effort delivery of an operational message to the maintainer."""
    prefixed = f"\u26a0\ufe0f predoc-pipeline: {message}"
    if not settings.telegram_bot_token or not settings.alert_chat_id:
        log.warning("alert_undelivered", reason="admin chat not configured", message=message)
        return
    try:
        with TelegramClient(bot_token=settings.telegram_bot_token) as client:
            client.send_plain(chat_id=settings.alert_chat_id, text=prefixed)
    except TelegramError as exc:
        log.error("alert_delivery_failed", error=str(exc), message=message)
