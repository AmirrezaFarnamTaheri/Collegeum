"""Maintainer alerts.

Operational diagnostics go to internal logs and health artifacts by default.
Telegram delivery is opt-in only, and requires an explicit, distinct positive
private admin chat ID. The vacancy broadcast destination and subscribers never
receive operational errors or log details.
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
        if exc.status == 403:
            log.error(
                "alert_delivery_failed",
                error=str(exc),
                message=message,
                advice=(
                    "The configured admin recipient must open this bot in a private "
                    "chat and press Start, or unblock it. Public channel delivery "
                    "is independent; do not rotate a working bot token."
                ),
            )
        else:
            log.error("alert_delivery_failed", error=str(exc), message=message)
