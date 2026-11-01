"""Private Telegram subscriber and admin navigation.

No callback grants authority: a private-chat sender is revalidated on every
button press. Mutating callbacks are stored with encrypted state so repeated
updates never invert preferences twice.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..ingest.career import load_career
from ..logging_setup import get_logger
from ..settings import Settings
from .admin import admin_id, audit, buttons, render
from .feedback import FeedbackStore
from .subscriptions import LOOKBACK_DAYS, matching, parse_toggle, private_user_id
from .telegram import TelegramError
from .ui import (
    ACADEMIC,
    LIFE_SCIENCES,
    MAX_LATEST_PAGES,
    language,
    latest_panel,
    menu,
    sources_panel,
)

log = get_logger(__name__)


def _safe_admin_render(
    settings: Settings, store: FeedbackStore, page: str = "status",
) -> str:
    """Display-only cache failures must not stall the global update cursor."""
    try:
        return render(settings, store, page=page)
    except (OSError, RuntimeError, ValueError, sqlite3.DatabaseError) as exc:
        log.warning("telegram_admin_snapshot_unavailable", error=type(exc).__name__)
        return (
            "<b>Collegeum · Admin</b>\n"
            "Status is temporarily unavailable. Inspect pipeline logs or "
            "restore the local cache. Subscriber commands remain active."
        )


def _reply_callback(bot: Any, callback_id: str, text: str = "") -> None:
    try:
        bot.call("answerCallbackQuery", {
            "callback_query_id": callback_id, "text": text[:170],
            "cache_time": 0,
        })
    except TelegramError:
        pass  # Old buttons can expire; state is already committed.


def _update_panel(
    bot: Any, cq: dict[str, Any], html: str, keyboard: dict[str, Any],
) -> None:
    message = cq.get("message") or {}
    chat = message.get("chat") or {}
    identifier = message.get("message_id")
    if type(identifier) is not int or type(chat.get("id")) is not int:
        return
    try:
        bot.call("editMessageText", {
            "chat_id": chat["id"], "message_id": identifier,
            "text": html, "parse_mode": "HTML", "reply_markup": keyboard,
            "link_preview_options": {"is_disabled": True},
        })
    except TelegramError:
        # A stale or already-identical panel must not roll back a saved change.
        pass


def _latest(
    store: FeedbackStore, chat_id: int, academic: list[sqlite3.Row],
    settings: Settings, page: int = 0, lookback_days: int = 14,
) -> tuple[str, dict[str, Any]]:
    member = store.subscriber(chat_id)
    if member is None or not member["topics"]:
        return menu(member, "home")
    try:
        careers = load_career(settings.career_state_path)
    except (OSError, UnicodeError, ValueError):
        # A damaged external feed must never poison the Telegram update cursor.
        careers = []
        degraded = True
    else:
        degraded = False
    results = matching(
        member, academic, careers, preview=True, lookback_days=lookback_days,
    )
    text, keyboard = latest_panel(
        results, page=page, lang=language(member), lookback_days=lookback_days,
    )
    if degraded:
        notice = ("⚠️ منبع مشاغل موقتاً در دسترس نیست."
                  if language(member) == "fa" else
                  "⚠️ Career listings are temporarily unavailable.")
        text += "\n\n" + notice
    return text, keyboard


def private_message(
    bot: Any, msg: dict[str, Any], store: FeedbackStore, settings: Settings,
    academic: list[sqlite3.Row], summary: dict[str, int],
) -> bool:
    """Handle subscriber commands; preserve the existing owner-only /help."""
    chat_id = private_user_id(msg)
    if chat_id is None:
        return False
    tokens = str(msg.get("text") or "").split(maxsplit=1)
    if not tokens:
        return False
    command = tokens[0].lower().split("@")[0]
    pages = {
        "/start": "home", "/settings": "home", "/subscribe": "subscriptions",
        "/subscriptions": "subscriptions", "/regions": "academic_regions",
        "/status": "home", "/more": "more", "/academic": "academic",
        "/careers": "careers", "/markets": "careers", "/guide": "help",
        "/lifesciences": "life_sciences",
        "/stop": "stop", "/delete": "stop", "/help": "help",
        "/sources": "sources", "/delivery": "delivery",
        "/privacy": "privacy",
    }
    if command not in pages and command not in {
        "/latest", "/admin", "/reconcile", "/pause", "/resume",
    }:
        return False
    summary["received"] += 1
    if not store.key:
        bot.send(str(chat_id), "Private alerts require encrypted storage.")
        summary["commands"] += 1
        return True

    if command == "/reconcile":
        if chat_id != admin_id(settings):
            summary["ignored"] += 1
            return True
        args = tokens[1].split() if len(tokens) > 1 else []
        usage = (
            "Use /reconcile CHAT_ID KEY sent MESSAGE_ID, or "
            "/reconcile CHAT_ID KEY absent CONFIRM_NOT_DELIVERED. "
            "Verify the chat independently before recording an outcome."
        )
        if len(args) != 4:
            bot.send(str(chat_id), usage)
            summary["commands"] += 1
            return True
        chat, key, outcome, evidence = args
        if not chat.isascii() or not chat.isdecimal() or int(chat) <= 0:
            bot.send(str(chat_id), usage)
            summary["commands"] += 1
            return True
        if len(key) > 256 or not key.startswith(("academic:", "career:")):
            bot.send(str(chat_id), usage)
            summary["commands"] += 1
            return True
        try:
            if outcome == "sent" and evidence.isascii() and evidence.isdecimal():
                store.resolve_delivery(
                    int(chat), key, confirmed_sent=True, message_id=int(evidence),
                )
            elif outcome == "absent" and evidence == "CONFIRM_NOT_DELIVERED":
                store.resolve_delivery(int(chat), key, confirmed_absent=True)
            else:
                raise ValueError("Invalid reconciliation evidence")
            store.save()
        except ValueError:
            bot.send(
                str(chat_id),
                "Reconciliation refused: check the delivery key, state and evidence.",
            )
        else:
            bot.send(str(chat_id), "Verified private delivery outcome saved.")
        summary["commands"] += 1
        return True

    if command == "/admin":
        if chat_id != admin_id(settings):
            summary["ignored"] += 1
            return True
        html = _safe_admin_render(settings, store)
        keyboard = buttons(paused=bool(store.data["ops"]["paused"]), page="status")
    elif command in ("/pause", "/resume"):
        member = store.subscriber(chat_id)
        if member is None:
            html, keyboard = menu(None, "home")
            html += "\n\nSelect a topic before changing notification settings."
        else:
            store.set_paused(chat_id, command == "/pause")
            store.save()
            html, keyboard = menu(member)
    elif command == "/latest":
        html, keyboard = _latest(store, chat_id, academic, settings)
    elif command == "/sources":
        html, keyboard = sources_panel(
            settings.career_health_path, lang=language(store.subscriber(chat_id)),
        )
    else:
        html, keyboard = menu(store.subscriber(chat_id), pages[command])
    bot.send(str(chat_id), html, keyboard)
    summary["commands"] += 1
    return True


def _page(
    raw: str, member: dict[str, Any] | None, store: FeedbackStore,
    user_id: int, settings: Settings, academic: list[sqlite3.Row],
) -> tuple[str, dict[str, Any]] | None:
    if raw.startswith("sub:p:latest"):
        parts = raw.split(":")
        if raw == "sub:p:latest":
            return _latest(store, user_id, academic, settings)
        if (len(parts) == 4 and parts[:3] == ["sub", "p", "latest"]
                and parts[3].isascii() and parts[3].isdecimal()
                and 0 <= int(parts[3]) < 10):
            # Previously sent page-only buttons remain usable at 14 days.
            return _latest(store, user_id, academic, settings, int(parts[3]))
        if (len(parts) == 5 and parts[:3] == ["sub", "p", "latest"]
                and parts[3] in {str(days) for days in LOOKBACK_DAYS}
                and len(parts[4]) <= 3 and parts[4].isascii()
                and parts[4].isdecimal() and int(parts[4]) < MAX_LATEST_PAGES):
            return _latest(store, user_id, academic, settings,
                           int(parts[4]), lookback_days=int(parts[3]))
        return None
    if not raw.startswith("sub:p:"):
        return None
    target = raw[6:]
    if target == "sources":
        return sources_panel(settings.career_health_path, lang=language(member))
    if target in (
        "home", "subscriptions", "academic", "academic_regions",
        "life_sciences", "careers", "markets", "delivery",
        "privacy", "help", "more", "stop",
    ):
        return menu(member, target)
    return None


def private_callback(
    bot: Any, cq: dict[str, Any], store: FeedbackStore, settings: Settings,
    summary: dict[str, int], academic: list[sqlite3.Row] | None = None,
) -> bool:
    """Process verified private callbacks; always acknowledge button presses."""
    raw = cq.get("data")
    if not isinstance(raw, str) or not raw.startswith(("sub:", "adm:")):
        return False
    callback_id = str(cq.get("id") or "")
    user_id = private_user_id({
        "chat": (cq.get("message") or {}).get("chat"),
        "from": cq.get("from"),
    })
    if user_id is None or not callback_id or not store.key:
        summary["ignored"] += 1
        if callback_id:
            _reply_callback(bot, callback_id)
        return True
    if not 1 <= len(raw.encode("utf-8")) <= 64:
        _reply_callback(bot, callback_id, "Invalid button")
        summary["ignored"] += 1
        return True
    notification = ""
    academic = academic or []

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
                + ("Pause private alerts? Collection and public publication continue."
                   if action == "pause"
                   else "Resume private alerts? Uncertain sends remain held.")
            )
            keyboard = {"inline_keyboard": [
                [{"text": "Confirm", "callback_data": "adm:confirm:" + action}],
                [{"text": "Cancel", "callback_data": "adm:status"}],
            ]}
        elif len(parts) == 3 and parts[:2] == ["adm", "confirm"] and (
            parts[2] in ("pause", "resume")
        ):
            if not store.callback_seen(callback_id):
                audit(store, user_id, parts[2])
                store.remember_callback(callback_id)
                store.save()
                summary["taps"] += 1
            html = _safe_admin_render(settings, store)
            keyboard = buttons(paused=bool(store.data["ops"]["paused"]), page="status")
            notification = "Saved"
        elif action in ("status", "runs", "queue", "cache", "recovery"):
            html = _safe_admin_render(settings, store, page=action)
            keyboard = buttons(paused=bool(store.data["ops"]["paused"]), page=action)
        else:
            _reply_callback(bot, callback_id, "Button expired. Try /admin.")
            return True
    else:
        member = store.subscriber(user_id)
        # Never let an unauthenticated signup storm stall later /stop updates.
        from .feedback import MAX_SUBSCRIBERS
        if (member is None and len(store.subscribers) >= MAX_SUBSCRIBERS
                and (parse_toggle(raw) is not None or raw.startswith(
                    ("sub:b:", "sub:a:", "sub:l:", "sub:r:")
                ))):
            _reply_callback(bot, callback_id, "Subscriptions are currently full.")
            return True
        if member is None and raw in (
            "sub:a:pause", "sub:a:resume", "sub:d:mode",
            "sub:d:limit", "sub:d:quiet", "sub:d:zone",
        ):
            _reply_callback(bot, callback_id, "Choose a topic first.")
            _update_panel(bot, cq, *menu(None, "home"))
            return True
        visible = _page(raw, member, store, user_id, settings, academic)
        if visible is not None:
            html, keyboard = visible
        else:
            parsed = parse_toggle(raw)
            mutation = False
            if parsed is not None:
                kind, option = parsed
                if not store.callback_seen(callback_id):
                    store.toggle_subscription(user_id, kind, option)
                    mutation = True
                target = (
                    "life_sciences" if option == LIFE_SCIENCES else
                    "academic" if option in ACADEMIC else "careers"
                ) if kind == "topics" else "careers"
            elif raw.startswith("sub:r:"):
                from .subscriptions import ACADEMIC_REGIONS
                region = raw.removeprefix("sub:r:")
                if region not in ACADEMIC_REGIONS and region != "all":
                    _reply_callback(bot, callback_id, "Invalid region")
                    return True
                if not store.callback_seen(callback_id):
                    store.toggle_academic_region(user_id, region)
                    mutation = True
                target = "academic_regions"
            elif raw in ("sub:a:pause", "sub:a:resume"):
                if not store.callback_seen(callback_id):
                    store.set_paused(user_id, raw.endswith(":pause"))
                    mutation = True
                target = "home"
            elif raw in ("sub:l:fa", "sub:l:en"):
                if not store.callback_seen(callback_id):
                    store.set_language(user_id, raw[-2:])
                    mutation = True
                target = "home"
            elif raw in ("sub:d:mode", "sub:d:limit", "sub:d:quiet", "sub:d:zone"):
                member = store.subscriber(user_id)
                if not store.callback_seen(callback_id):
                    if raw == "sub:d:mode":
                        old = member.get("delivery_mode", "instant") if member else "instant"
                        value = "digest" if old == "instant" else "instant"
                        store.set_delivery_preference(user_id, "delivery_mode", value)
                    elif raw == "sub:d:limit":
                        from .feedback import DAILY_LIMITS
                        old = member.get("daily_limit", 6) if member else 6
                        next_limit = DAILY_LIMITS[
                            (DAILY_LIMITS.index(old) + 1) % len(DAILY_LIMITS)
                        ]
                        store.set_delivery_preference(user_id, "daily_limit", next_limit)
                    elif raw == "sub:d:quiet":
                        old = bool(member and member.get("quiet_hours"))
                        store.set_delivery_preference(user_id, "quiet_hours", not old)
                    else:
                        from .feedback import DELIVERY_ZONES
                        old = member.get("timezone", "UTC") if member else "UTC"
                        value = DELIVERY_ZONES[
                            (DELIVERY_ZONES.index(old) + 1) % len(DELIVERY_ZONES)
                        ]
                        store.set_delivery_preference(user_id, "timezone", value)
                    mutation = True
                target = "delivery"
            elif raw.startswith("sub:b:"):
                parts = raw.split(":")
                if (len(parts) != 4 or parts[2] not in ("academic", "careers")
                        or parts[3] not in ("on", "off")):
                    _reply_callback(bot, callback_id, "Invalid choice")
                    return True
                if not store.callback_seen(callback_id):
                    store.set_topics_group(user_id, parts[2], parts[3] == "on")
                    mutation = True
                target = parts[2]
            elif raw == "sub:stop:yes":
                if not store.callback_seen(callback_id):
                    store.remove_subscriber(user_id)
                    mutation = True
                target = "home"
            else:
                _reply_callback(bot, callback_id, "Button expired. Use /settings.")
                return True
            if mutation:
                store.remember_callback(callback_id)
                store.save()
                summary["taps"] += 1
            html, keyboard = menu(store.subscriber(user_id), target)
            notification = "Saved" if mutation else ""

    _reply_callback(bot, callback_id, notification)
    _update_panel(bot, cq, html, keyboard)
    return True
