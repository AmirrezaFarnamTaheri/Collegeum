"""Two-way Telegram: commands and ✅ ❌ 📝 buttons.

Commands you can send to the bot:

    /positions  all open positions, soonest deadline first
    /applied    positions you marked 📝 applied
    /valid      positions you marked ✅
    /hidden     positions you marked ❌ (tap ❌ again to bring one back)
    /help       what the buttons mean

There is no always-on server. GitHub Actions runs ``predoc-pipeline
telegram-sync`` every 30 minutes during the day (and at the start of the daily
run). Each run reads the messages and button taps that arrived since the last
one (Telegram keeps them for 24 hours), answers them, and saves your marks to
``data/feedback.json``.

Only the owner (the private chat in TELEGRAM_PUBLIC_CHANNEL_ID or
TELEGRAM_ADMIN_CHAT_ID) is answered; everybody else is ignored.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from html import escape as escape_attribute
from typing import Any

import httpx

from .. import state
from ..boards.config import load_preferences
from ..core.db import Database
from ..core.db import init as init_db
from ..core.textproc import escape_telegram_html as esc
from ..core.textproc import truncate_utf16
from ..core.timeparse import parse_datetime, utcnow
from ..logging_setup import get_logger
from ..routing import Router
from ..settings import Settings
from .feedback import (
    APPLIED,
    ID_PREFIX,
    INVALID,
    STATUS_BY_CODE,
    VALID,
    FeedbackStore,
    load_chat_state,
    save_state,
)
from .keyboards import LEGEND, feedback_row, parse_callback, rebuild
from .telegram import TelegramClient, TelegramError, deadline_label, pack_html_blocks

log = get_logger(__name__)

__all__ = ["COMMANDS", "telegram_sync", "select_rows", "build_pages", "command_of"]

COMMANDS = [
    ("positions", "All open positions, soonest deadline first"),
    ("applied", "Positions you marked 📝 applied"),
    ("valid", "Positions you marked ✅ interested"),
    ("hidden", "Positions you marked ❌ (to restore one)"),
    ("help", "How the buttons work"),
]
COMMANDS_VERSION = 1
ALIASES = {
    "positions": "positions", "position": "positions", "list": "positions", "jobs": "positions",
    "open": "positions", "applied": "applied", "valid": "valid", "interested": "valid",
    "saved": "valid", "hidden": "hidden", "invalid": "hidden", "help": "help", "start": "help",
}
HELP = (
    "🤖 <b>Predoc bot</b>\n\n"
    "/positions: all open positions, soonest deadline first\n"
    "/applied: the ones you applied to\n"
    "/valid: the ones you marked ✅\n"
    "/hidden: the ones you marked ❌\n\n"
    "Under every position:\n"
    "✅ = interested  ·  ❌ = not for me (it disappears everywhere)  ·  "
    "📝 = I applied (moves to /applied)\n"
    "Tap the same button again to undo.\n\n"
    "⏱ I check for messages every 30 minutes during the day, so replies can take up to "
    "half an hour."
)
DONE = {
    VALID: "✅ Marked as interested",
    INVALID: "❌ Hidden, you won't see it again",
    APPLIED: "📝 Marked as applied",
    None: "↩️ Mark removed",
}
TITLES = {
    "positions": "📋 <b>{n} open position{s}</b>, soonest deadline first",
    "applied": "📝 <b>{n} position{s} you applied to</b>",
    "valid": "✅ <b>{n} position{s} you marked as interesting</b>",
    "hidden": "❌ <b>{n} hidden position{s}</b> (tap ❌ again to bring one back)",
}
EMPTY = {
    "positions": "📋 No open positions right now. New ones arrive with the morning run.",
    "applied": "📝 You haven't marked anything as applied yet. Tap 📝 under a position.",
    "valid": "✅ Nothing marked as interesting yet. Tap ✅ under a position.",
    "hidden": "❌ Nothing hidden.",
}


# ---------------------------------------------------------------------------- lists
def _deadline(row: sqlite3.Row) -> Any:
    return parse_datetime(row["deadline"])


def _is_open(row: sqlite3.Row) -> bool:
    if row["closed_at"] or row["expired_at"]:
        return False
    when = _deadline(row)
    return not (when and when < utcnow())


def _sort(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    far = parse_datetime("9999-12-31T00:00:00Z")
    return sorted(rows, key=lambda r: (_deadline(r) or far, -(r["confidence"] or 0), r["title"]))


def select_rows(kind: str, rows: list[sqlite3.Row], store: FeedbackStore) -> list[sqlite3.Row]:
    if kind == "positions":
        return _sort([r for r in rows if _is_open(r)
                      and store.status(r["url_hash"]) not in (INVALID, APPLIED)])
    if kind == "valid":
        return _sort([r for r in rows if store.status(r["url_hash"]) == VALID and _is_open(r)])
    if kind == "applied":
        return _sort([r for r in rows if store.status(r["url_hash"]) == APPLIED])
    if kind == "hidden":
        return _sort([r for r in rows if store.status(r["url_hash"]) == INVALID])
    return []


def listing_block(row: sqlite3.Row, n: int, store: FeedbackStore) -> str:
    status = store.status(row["url_hash"])
    mark = {VALID: " ✅", APPLIED: " 📝", INVALID: " ❌"}.get(status or "", "")
    where = ", ".join(x for x in (row["city"], row["country"]) if x) or "location not stated"
    lines = [
        f"<b>{n}. {esc(truncate_utf16(row['title'], 140))}</b>{mark}",
        f"🏛 {esc(truncate_utf16(row['institution'], 110))} — {esc(truncate_utf16(where, 120))}",
        f"⏳ {esc(truncate_utf16(deadline_label(row['deadline'], row['deadline_note']), 120))} · "
        f'<a href="{escape_attribute(row["apply_url"], quote=True)}">open ad</a>',
    ]
    marked_at = store.marked_at(row["url_hash"])
    if status == APPLIED and marked_at:
        note = f"📝 applied on {marked_at[:10]}"
        if row["closed_at"]:
            note += " · ⚠️ ad now closed"
        lines.append(note)
    return "\n".join(lines)


def build_pages(
    kind: str,
    rows: list[sqlite3.Row],
    store: FeedbackStore,
    *,
    page_size: int = 5,
    max_items: int = 60,
    site_url: str = "",
) -> list[tuple[str, dict[str, Any] | None]]:
    """The messages (text, buttons) that answer one command."""
    if not rows:
        return [(EMPTY[kind], None)]
    if max_items < 1:
        raise ValueError("bot command max_items must be positive")
    shown = rows[:max_items]
    blocks = [listing_block(row, i, store) for i, row in enumerate(shown, 1)]
    head = TITLES[kind].format(n=len(rows), s="" if len(rows) == 1 else "s") + "\n\n"
    footer = ""
    if len(rows) > len(shown):
        more = len(rows) - len(shown)
        footer += f"\n\n…and {more} more" + (
            f' on the <a href="{escape_attribute(site_url, quote=True)}">dashboard</a>.'
            if site_url else "."
        )
    if kind == "positions":
        n_applied = len(store.with_status(APPLIED))
        if n_applied:
            footer += f"\n\n📝 You've applied to {n_applied}: send /applied"
    footer += f"\n\n<i>{esc(LEGEND)}</i>"
    pages: list[tuple[str, dict[str, Any] | None]] = []
    for page in pack_html_blocks(blocks, header=head, footer=footer, page_size=min(page_size, 30)):
        chunk = shown[page.start:page.end]
        buttons = [feedback_row(r["url_hash"], store.status(r["url_hash"]), page.start + i + 1)
                   for i, r in enumerate(chunk)]
        pages.append((page.html, {"inline_keyboard": buttons}))
    return pages


def command_of(text: str | None) -> str | None:
    if not text:
        return None
    word = text.strip().split()[0].lower().lstrip("/").split("@")[0]
    return ALIASES.get(word, "help")


# ---------------------------------------------------------------------------- sync
class _Bot:
    def __init__(self, client: TelegramClient, sleep: Callable[[float], None]):
        self.client, self.sleep = client, sleep

    def send(self, chat_id: str, html: str, keyboard: dict[str, Any] | None = None) -> None:
        self.client.send_message(chat_id=chat_id, html=html, keyboard=keyboard, sleep=self.sleep)

    def call(self, method: str, payload: dict[str, Any]) -> Any:
        return self.client.call(method, payload, sleep=self.sleep)


def telegram_sync(
    settings: Settings,
    *,
    http_client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    page_size: int | None = None,
    max_items: int | None = None,
) -> dict[str, int]:
    """Answer everything sent to the bot since the last run. Safe to run as often as you like."""
    from ..boards.config import load_preferences

    tg_prefs = load_preferences(settings.preferences_config).telegram
    page_size = max(1, page_size or tg_prefs.list_page_size)
    max_items = max(1, max_items or tg_prefs.list_max)
    summary = {"received": 0, "commands": 0, "taps": 0, "ignored": 0, "failed": 0, "dropped": 0}
    owners = settings.owner_ids
    if not settings.telegram_bot_token or not owners:
        log.warning("telegram_sync_skipped",
                    reason="set TELEGRAM_BOT_TOKEN and your own chat id "
                           "(TELEGRAM_PUBLIC_CHANNEL_ID or TELEGRAM_ADMIN_CHAT_ID)")
        return summary

    tg = TelegramClient(bot_token=settings.telegram_bot_token, client=http_client)
    bot = _Bot(tg, sleep)
    try:
        chat_state = load_chat_state(settings.telegram_state_path)
        store = FeedbackStore.from_settings(settings)
    except Exception:
        tg.close()
        raise
    try:
        if chat_state.get("commands_version") != COMMANDS_VERSION:
            try:
                bot.call("setMyCommands", {"commands": [
                    {"command": c, "description": d} for c, d in COMMANDS]})
                chat_state["commands_version"] = COMMANDS_VERSION
            except TelegramError as exc:
                log.warning("set_commands_failed", error=str(exc))

        payload: dict[str, Any] = {"timeout": 0,
                                   "allowed_updates": ["message", "callback_query"]}
        if chat_state.get("offset"):
            payload["offset"] = chat_state["offset"]
        try:
            updates = bot.call("getUpdates", payload) or []
        except TelegramError as exc:
            if exc.status == 409:
                log.error("telegram_webhook_set",
                          hint="a webhook is set for this bot; commands only work without one")
                return summary
            if exc.status in (401, 403, 404):
                log.warning("telegram_auth_or_chat_failed", error=str(exc))
                return summary
            raise
        if not updates:
            if chat_state.get("exports_pending"):
                if _refresh_public_exports(settings, store):
                    chat_state["exports_pending"] = False
                else:
                    summary["failed"] += 1
            save_state(settings.telegram_state_path, chat_state)
            return summary

        init_db(settings.db_path)
        with Database(settings.db_path) as db:
            state.restore_if_needed(db, settings.state_path)
            rows = list(db.published_listings())
        by_prefix = {r["url_hash"][:ID_PREFIX]: r for r in rows}
        changed = False

        for update in updates:
            update_id = int(update["update_id"])
            try:
                if "callback_query" in update:
                    changed |= _handle_tap(bot, update["callback_query"], by_prefix, store,
                                           owners, summary)
                elif "message" in update:
                    _handle_message(bot, update["message"], rows, store, owners, summary,
                                    page_size=page_size, max_items=max_items,
                                    site_url=settings.site_url)
            except Exception as exc:  # noqa: BLE001
                if _is_retryable(exc):
                    # Do not acknowledge: this update (and everything after it) is
                    # fetched again next run. Marks are replay-safe (callback ids).
                    summary["failed"] += 1
                    log.warning("update_deferred", update_id=update_id, error=str(exc))
                    break
                summary["dropped"] += 1  # a poison update must not block the queue forever
                log.warning("update_dropped", update_id=update_id, error=str(exc))
            chat_state["offset"] = update_id + 1
            if changed:
                chat_state["exports_pending"] = True
            store.save()
            save_state(settings.telegram_state_path, chat_state)

        store.save()
        save_state(settings.telegram_state_path, chat_state)
        if changed or chat_state.get("exports_pending"):
            if _refresh_public_exports(settings, store):
                chat_state["exports_pending"] = False
                save_state(settings.telegram_state_path, chat_state)
            else:
                summary["failed"] += 1
        log.info("telegram_sync", **summary)
        return summary
    finally:
        tg.close()


def _is_retryable(exc: BaseException) -> bool:
    """Only explicit permanent API rejection justifies dropping an update.

    Local processing/storage failures have unknown outcomes and must not
    silently acknowledge the user's request.
    """
    if isinstance(exc, TelegramError):
        return not exc.permanent
    return True


def _refresh_public_exports(settings: Settings, store: FeedbackStore) -> bool:
    """A ❌ should also take the position off the dashboard and the RSS feed."""
    try:
        router = Router(load_preferences(settings.preferences_config))
        with Database(settings.db_path) as db:
            state.export_dashboard(db, settings.dashboard_json, hidden=store.hidden, router=router)
            state.export_feed(db, settings.feed_path, site_url=settings.site_url,
                              hidden=store.hidden, router=router)
        return True
    except Exception as exc:  # noqa: BLE001 - retain durable retry intent
        log.warning("export_refresh_failed", error=str(exc))
        return False


def _chat_id(obj: dict[str, Any] | None) -> int | None:
    try:
        return int((obj or {}).get("id"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _handle_message(
    bot: _Bot,
    msg: dict[str, Any],
    rows: list[sqlite3.Row],
    store: FeedbackStore,
    owners: set[int],
    summary: dict[str, int],
    **page_opts: Any,
) -> None:
    chat = _chat_id(msg.get("chat"))
    if chat not in owners:
        summary["ignored"] += 1
        return
    kind = command_of(msg.get("text"))
    if not kind:
        return
    summary["received"] += 1
    if kind == "help":
        bot.send(str(chat), HELP)
        summary["commands"] += 1
        return
    for text, keyboard in build_pages(kind, select_rows(kind, rows, store), store, **page_opts):
        bot.send(str(chat), text, keyboard)
    summary["commands"] += 1


def _handle_tap(
    bot: _Bot,
    cq: dict[str, Any],
    by_prefix: dict[str, sqlite3.Row],
    store: FeedbackStore,
    owners: set[int],
    summary: dict[str, int],
) -> bool:
    """Returns True when public exports need refreshing, including replay recovery."""
    if _chat_id(cq.get("from")) not in owners:
        summary["ignored"] += 1
        return False
    parsed = parse_callback(cq.get("data"))
    if not parsed:
        return False
    code, prefix = parsed
    row = by_prefix.get(prefix)
    reply = "This position is no longer in the list."
    changed = False
    callback_id = cq.get("id")
    replayed = store.callback_seen(callback_id)
    if row is not None and replayed:
        reply = DONE[store.status(row["url_hash"])]  # already applied once; do not toggle
        changed = True  # A prior crash may have saved the mark before refreshing exports.
    elif row is not None:
        wanted = STATUS_BY_CODE[code]
        new = None if store.status(row["url_hash"]) == wanted else wanted  # tap again = undo
        store.set(row["url_hash"], new, title=row["title"], institution=row["institution"],
                  url=row["apply_url"])
        store.remember_callback(callback_id)
        reply = DONE[new]
        summary["taps"] += 1
        changed = True
    try:  # Telegram rejects answers to taps older than a few minutes; harmless
        bot.call("answerCallbackQuery", {"callback_query_id": cq["id"], "text": reply})
    except (TelegramError, KeyError) as exc:
        log.debug("answerCallbackQuery failed for query %s: %s", cq.get("id"), exc)
    message = cq.get("message") or {}
    if message.get("message_id") and message.get("reply_markup"):
        def status_of(pfx: str) -> str | None:
            r = by_prefix.get(pfx)
            return store.status(r["url_hash"]) if r is not None else None

        try:
            bot.call("editMessageReplyMarkup", {
                "chat_id": (message.get("chat") or {}).get("id"),
                "message_id": message["message_id"],
                "reply_markup": rebuild(message["reply_markup"], status_of),
            })
        except TelegramError as exc:  # e.g. "message is not modified"
            log.debug("redraw_failed", error=str(exc))
    return changed

