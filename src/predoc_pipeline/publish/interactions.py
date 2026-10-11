"""Telegram private-chat interaction layer (subscriptions and admin tools)."""

from __future__ import annotations

import sqlite3
from typing import Any

from ..ingest.career import load_career
from ..settings import Settings
from .admin import admin_id, audit, buttons, render
from .feedback import FeedbackStore
from .subscriptions import (
    matching, menu, parse_toggle, private_user_id, render_alert,
)
from .telegram import TelegramError


def _reply_callback(bot: Any, callback_id: str, text: str) -> None:
    try:
        bot.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:170]})
    except TelegramError:
        pass  # expired button acknowledgements do not invalidate stored preferences


def _update_panel(
    bot: Any, cq: dict[str, Any], html: str, keyboard: dict[str, Any],
) -> None:
    msg = cq.get("message") or {}
    chat = msg.get("chat") or {}
    message_id = msg.get("message_id")
    if not message_id:
        return
    try:
        bot.call("editMessageText", {
            "chat_id": chat["id"], "message_id": message_id,
            "text": html, "parse_mode": "HTML", "reply_markup": keyboard,
            "link_preview_options": {"is_disabled": True},
        })
    except TelegramError:
        # Telegram can reject no-op edits, old messages or revoked permissions;
        # the durable preference change already completed.
        pass


def private_message(
    bot: Any, msg: dict[str, Any], store: FeedbackStore, settings: Settings,
    academic: list[sqlite3.Row], summary: dict[str, int],
) -> bool:
    """True if handled. Old owner-only mark/list commands remain a fallback."""
    user_id = private_user_id(msg)
    if user_id is None:
        return False
    words = str(msg.get("text") or "").split(maxsplit=1)
    if not words:  # stickers, photos and other non-text updates are not commands
        return False
    text = words[0].lower().split("@")[0]
    if text not in {"/start", "/settings", "/subscribe", "/stop", "/latest", "/admin"}:
        return False
    summary["received"] += 1
    if not store.key:
        bot.send(str(user_id), "Personal alerts are unavailable until encrypted storage is set up.")
        return True
    if text == "/admin":
        if user_id != admin_id(settings):
            summary["ignored"] += 1
            return True
        html = render(settings, store)
        bot.send(str(user_id), html, buttons(
            paused=bool(store.data.get("ops", {}).get("paused")),
        ))
    elif text == "/stop":
        store.remove_subscriber(user_id)
        store.save()  # commit an opt-out before sending its acknowledgement
        bot.send(str(user_id), "You are unsubscribed. Your active preferences and "
                 "delivery records were removed. Use /start to subscribe again.")
    elif text == "/latest":
        member = store.subscriber(user_id)
        if member is None or not member["topics"]:
            bot.send(str(user_id), "Choose interests with /settings first.")
        else:
            jobs = matching(
                member, academic, load_career(settings.career_state_path),
                preview=True,
            )
            if not jobs:
                bot.send(str(user_id), "No recent matching vacancies yet. "
                         "Your alerts remain active for future posts.")
            else:
                # Explicit user-requested previews need no send receipts.
                for job in jobs[:5]:
                    bot.send(str(user_id), render_alert(job))
    else:
        html, keyboard = menu(store.subscriber(user_id))
        bot.send(str(user_id), html, keyboard)
    summary["commands"] += 1
    return True


def private_callback(
    bot: Any, cq: dict[str, Any], store: FeedbackStore, settings: Settings,
    summary: dict[str, int],
) -> bool:
    raw = cq.get("data")
    if not isinstance(raw, str) or not raw.startswith(("sub:", "adm:")):
        return False
    user_id = private_user_id({
        "chat": (cq.get("message") or {}).get("chat"),
        "from": cq.get("from"),
    })
    if user_id is None:
        summary["ignored"] += 1
        return True
    callback_id = str(cq.get("id") or "")
    if not callback_id or not store.key:
        summary["ignored"] += 1
        return True
    if raw.startswith("adm:"):
        if user_id != admin_id(settings):
            summary["ignored"] += 1
            _reply_callback(bot, callback_id, "Not authorized")
            return True
        parts = raw.split(":")
        action = parts[1] if len(parts) == 2 else ""
        if action in ("pause", "resume"):
            html = (
                "<b>Confirm</b>\n"
                + ("Pause private notifications? Collection and public "
                   "publishing will continue." if action == "pause"
                   else "Resume private notifications? Uncertain sends stay held.")
            )
            keyboard = {"inline_keyboard": [
                [{"text": "Confirm", "callback_data": "adm:confirm:" + action}],
                [{"text": "Back", "callback_data": "adm:status"}],
            ]}
        elif len(parts) == 3 and parts[:2] == ["adm", "confirm"] and (
            parts[2] in ("pause", "resume")
        ):
            if not store.callback_seen(callback_id):
                audit(store, user_id, parts[2])
                store.remember_callback(callback_id)
                store.save()
            html = render(settings, store)
            keyboard = buttons(paused=bool(store.data["ops"]["paused"]))
            summary["taps"] += 1
        elif action in ("status", "runs", "queue", "cache"):
            html = render(settings, store, page=action)
            keyboard = buttons(paused=bool(store.data.get("ops", {}).get("paused")))
        else:
            _reply_callback(bot, callback_id, "Unknown admin action")
            return True
    else:
        parsed = parse_toggle(raw)
        if parsed is None:
            _reply_callback(bot, callback_id, "Unknown option")
            return True
        if not store.callback_seen(callback_id):
            kind, choice = parsed
            store.toggle_subscription(user_id, kind, choice)
            store.remember_callback(callback_id)
            store.save()  # preferences and callback ID are committed together
            summary["taps"] += 1
        html, keyboard = menu(store.subscriber(user_id))
    _reply_callback(bot, callback_id, "Saved")
    _update_panel(bot, cq, html, keyboard)
    return True
