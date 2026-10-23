"""Maintainer alerts.

Operational diagnostics go to internal logs and health artifacts by default.
Telegram delivery is opt-in only, and requires an explicit, distinct positive
private admin chat ID. The vacancy broadcast destination and subscribers never
receive operational errors or log details.

Delivery failures are themselves a failure mode: an alert that cannot be
delivered must not be silently swallowed, and it must not take the run down
either. ``notify_admin`` therefore reports *whether* the message was delivered
and never raises, so the caller can record an undelivered alert as a run
error instead of pretending the maintainer was told.
"""

from __future__ import annotations

from .logging_setup import get_logger
from .publish.telegram import TelegramClient, TelegramError
from .settings import Settings

log = get_logger(__name__)

__all__ = ["notify_admin"]


def notify_admin(settings: Settings, message: str) -> bool:
    """Best-effort delivery of an operational message to the maintainer.

    Returns True when the message was accepted by the Bot API, False when it
    was not delivered. Never raises: an alerting path must not be able to
    abort a pipeline run.
    """
    prefixed = f"\u26a0\ufe0f predoc-pipeline: {message}"
    if not settings.telegram_bot_token or not settings.alert_chat_id:
        log.warning(
            "alert_undelivered",
            reason="admin chat not configured",
            message=message,
            advice=(
                "Operational alerts need TELEGRAM_OPERATIONAL_ALERTS_ENABLED=true "
                "and a TELEGRAM_ADMIN_CHAT_ID that is a positive private user id "
                "and differs from TELEGRAM_PUBLIC_CHANNEL_ID."
            ),
        )
        return False
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
        return False
    except Exception as exc:  # pragma: no cover - defensive: alerting must not raise
        log.error("alert_delivery_failed", error=repr(exc), message=message)
        return False
    log.info("alert_delivered", message=message)
    return True
