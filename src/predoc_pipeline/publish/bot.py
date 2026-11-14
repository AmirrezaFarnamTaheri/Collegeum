"""Scheduled two-way Telegram subscriber, owner and administrator interactions.

General commands configure private opt-in alerts and browse job opportunities.
The administrator has scoped /admin and /reconcile commands. Legacy
feedback buttons remain owner-only. Shared GitHub Actions workflows serialize
state writers and checkpoint delivery intents before sending. Ambiguous sends
must be reconciled with verified evidence.

The service polls approximately every 30 minutes throughout the day, subject
to GitHub scheduler delays. It is not an always-online webhook server.
Incoming updates expire at Telegram after at most 24 hours.
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
from .interactions import private_callback, private_message
from .keyboards import LEGEND, feedback_row, parse_callback, rebuild
from .subscriptions import private_user_id
from .telegram import TelegramClient, TelegramError, deadline_label, pack_html_blocks

log = get_logger(__name__)

__all__ = ["COMMANDS", "telegram_sync", "select_rows", "build_pages", "command_of"]

COMMANDS = [
    ("start", "Open your job alert dashboard"),
    ("latest", "See recently found opportunities"),
    ("settings", "Choose topics and job markets"),
    ("delivery", "Digest, alert limit and quiet hours"),
    ("pause", "Pause your alerts"),
    ("resume", "Resume your alerts"),
    ("ask", "Ask questions about stored vacancies"),
    ("help", "How Collegeum alerts work"),
    ("stop", "Unsubscribe (with confirmation)"),
]
# Advanced commands remain available when typed or tapped; the Telegram
# command picker only exposes everyday actions rather than 24+ shortcuts.
OWNER_COMMANDS = [
    ("menu", "Browse your research shortlist"),
    ("positions", "Browse My matches"),
    ("search", "Search stored vacancies"),
    ("saved", "Saved and interesting roles"),
    ("applied", "Track applications"),
]
ADMIN_COMMAND = ("admin", "Operations and source health")
RECONCILE_COMMAND = ("reconcile", "Verify a private delivery outcome")
FA_COMMAND_DESCRIPTIONS = {
    "ask": "پرسش از اطلاعات فرصت‌ها",
    "forget": "پاک کردن زمینه گفت‌وگوی هوش مصنوعی",
    "start": "صفحه اصلی اعلان فرصت‌ها",
    "settings": "تنظیم موضوع‌ها و محدوده",
    "latest": "مرور تازه‌ترین فرصت‌ها",
    "lifesciences": "دکتری علوم زیستی در اروپا",
    "sources": "وضعیت منابع آگهی",
    "delivery": "تنظیمات دریافت اعلان",
    "privacy": "حریم خصوصی و نگهداری داده",
    "pause": "توقف اعلان‌ها",
    "resume": "ازسرگیری اعلان‌ها",
    "guide": "راهنمای استفاده",
    "help": "راهنمای استفاده",
    "stop": "لغو عضویت با تأیید",
    "delete": "حذف داده‌های فعال اشتراک",
}
COMMANDS_VERSION = 14
MAX_COMMANDS_PER_SYNC = 20
ALIASES = {
    "menu": "menu", "home": "menu", "more": "more", "search": "search", "new": "new",
    "closing": "closing", "ask": "ask", "forget": "forget",
    "positions": "positions", "position": "positions", "list": "positions", "jobs": "positions",
    "open": "positions", "applied": "applied", "valid": "valid", "interested": "valid",
    "saved": "valid", "hidden": "hidden", "invalid": "hidden", "help": "help",
    "ownerhelp": "help", "start": "help",
    "favorites": "favorites", "bookmarks": "favorites", "delete": "delete",
}
HELP = (
    "🤖 <b>Predoc bot</b>\n\n"
    "/positions: stored listings, nearest stated deadline first\n"
    "Check with the employer before applying; availability may have changed.\n"
    "/applied: the ones you applied to\n"
    "/valid: the ones you marked ✅\n"
    "/hidden: the ones you marked ❌\n\n"
    "Under every position:\n"
    "✅ = interested  ·  ❌ = not for me (it disappears everywhere)  ·  "
    "📝 = I applied (moves to /applied)\n"
    "Tap the same button again to undo.\n\n"
    "⏱ Replies are checked about twice per hour. GitHub Actions scheduling "
    "may delay the next check."
)
DONE = {
    VALID: "✅ Marked as interested",
    INVALID: "❌ Hidden, you won't see it again",
    APPLIED: "📝 Marked as applied",
    None: "↩️ Mark removed",
}
TITLES = {
    "positions": "📋 <b>{n} snapshot listing{s}</b>, soonest deadline first",
    "applied": "📝 <b>{n} position{s} you applied to</b>",
    "valid": "✅ <b>{n} position{s} you marked as interesting</b>",
    "hidden": "❌ <b>{n} hidden position{s}</b> (tap ❌ again to bring one back)",
}
EMPTY = {
    "positions": "📋 No matching listings in this snapshot. Review filters or check later.",
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
    snapshot_note = ("\n\n<i>Snapshot only: current availability is not independently verified.</i>"
                     if kind == "positions" else "")
    footer += snapshot_note
    footer += f"\n\n<i>{esc(LEGEND)}</i>"
    pages: list[tuple[str, dict[str, Any] | None]] = []
    for page in pack_html_blocks(blocks, header=head, footer=footer, page_size=min(page_size, 30)):
        chunk = shown[page.start:page.end]
        buttons = [feedback_row(r["url_hash"], store.status(r["url_hash"]), page.start + i + 1)
                   for i, r in enumerate(chunk)]
        # pack_html_blocks writes the footer on the last page only; every
        # earlier page also needs the disclosure. The packer reserves its budget.
        html = page.html + (snapshot_note if page.end < len(shown) else "")
        pages.append((html, {"inline_keyboard": buttons}))
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


def _refresh_commands(
    settings: Settings, bot: _Bot, chat_state: dict[str, Any], owners: set[int],
) -> None:
    """Update Telegram picker metadata without polling, sending, or changing state receipts."""
    if chat_state.get("commands_version") == COMMANDS_VERSION:
        return
    try:
        command_list = [
            {"command": c, "description": d} for c, d in COMMANDS
        ]
        bot.call("setMyCommands", {"commands": command_list})
        # Persian labels for users whose Telegram locale is Persian.
        bot.call("setMyCommands", {
            "scope": {"type": "all_private_chats"},
            "language_code": "fa",
            "commands": [
                {"command": c, "description": FA_COMMAND_DESCRIPTIONS[c]}
                for c, _ in COMMANDS
            ],
        })
        raw_admin = settings.telegram_admin_chat_id.strip()
        admin_chat = (
            int(raw_admin) if raw_admin.isascii()
            and raw_admin.isdecimal() and int(raw_admin) > 0
            else None
        )
        for chat_id in sorted(owners):
            scoped = [
                *command_list,
                *[
                    {"command": c, "description": desc}
                    for c, desc in OWNER_COMMANDS
                ],
            ]
            if chat_id == admin_chat:
                scoped.extend([
                    {"command": ADMIN_COMMAND[0], "description": ADMIN_COMMAND[1]},
                    {
                        "command": RECONCILE_COMMAND[0],
                        "description": RECONCILE_COMMAND[1],
                    },
                ])
            bot.call("setMyCommands", {
                "scope": {"type": "chat", "chat_id": chat_id},
                "commands": scoped,
            })
        chat_state["commands_version"] = COMMANDS_VERSION
    except TelegramError as exc:
        log.warning("set_commands_failed", error=str(exc))


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

    if settings.telegram_webhook_enabled:
        from .cloud import sync_cloud

        result = sync_cloud(settings, http_client=http_client)
        if settings.telegram_bot_token and settings.owner_ids:
            chat_state = load_chat_state(settings.telegram_state_path)
            if chat_state.get("commands_version") != COMMANDS_VERSION:
                tg = TelegramClient(bot_token=settings.telegram_bot_token, client=http_client)
                try:
                    _refresh_commands(settings, _Bot(tg, sleep), chat_state, settings.owner_ids)
                    if chat_state.get("commands_version") == COMMANDS_VERSION:
                        save_state(settings.telegram_state_path, chat_state)
                finally:
                    tg.close()
        return result
    tg_prefs = load_preferences(settings.preferences_config).telegram
    page_size = max(1, page_size or tg_prefs.list_page_size)
    max_items = max(1, max_items or tg_prefs.list_max)
    summary = {
        "received": 0, "commands": 0, "taps": 0, "ignored": 0,
        "failed": 0, "dropped": 0,
    }
    owners = settings.owner_ids
    if not settings.telegram_bot_token or not (owners or settings.feedback_encryption_key):
        log.warning("telegram_sync_skipped",
                    reason="set TELEGRAM_BOT_TOKEN and encrypted private subscriptions "
                           "or an owner Telegram chat ID")
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
        _refresh_commands(settings, bot, chat_state, owners)

        # Bound interactive processing so a command storm cannot monopolize
        # the ten-minute scheduled sync window. Unprocessed updates keep offset.
        payload: dict[str, Any] = {"timeout": 0, "limit": 100,
                                   "allowed_updates": ["message", "callback_query"]}
        if chat_state.get("offset"):
            payload["offset"] = chat_state["offset"]
        try:
            updates = bot.call("getUpdates", payload) or []
        except TelegramError as exc:
            if exc.status == 409:
                log.error("telegram_webhook_set",
                          hint="a webhook is set for this bot; commands only work without one")
                if store.subscribers:
                    raise  # never send to opted-in users when /stop cannot be received
                return summary
            if exc.status in (401, 403, 404):
                log.warning("telegram_auth_or_chat_failed", error=str(exc))
                if store.subscribers:
                    raise
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
        per_user_count: dict[int, int] = {}

        for update in updates:
            update_id = int(update["update_id"])
            message = update.get("message") or {}
            callback = update.get("callback_query") or {}
            if "callback_query" in update:
                user_id = private_user_id({
                    "from": callback.get("from"),
                    "chat": (callback.get("message") or {}).get("chat"),
                })
                raw = str(callback.get("data") or "")
                essential = raw in ("sub:p:stop", "sub:stop:yes", "sub:a:pause")
            else:
                user_id = private_user_id(message)
                raw = str(message.get("text") or "").strip().split(" ", 1)[0].lower()
                essential = raw.split("@", 1)[0] in ("/stop", "/delete", "/pause")
            if user_id is not None and user_id not in owners and not essential:
                per_user_count[user_id] = per_user_count.get(user_id, 0) + 1
            too_many = (
                user_id is not None and user_id not in owners and not essential
                and per_user_count[user_id] > MAX_COMMANDS_PER_SYNC
            )
            try:
                if too_many:
                    summary["throttled"] = summary.get("throttled", 0) + 1
                    if "callback_query" in update:
                        try:
                            bot.call("answerCallbackQuery", {
                                "callback_query_id": callback["id"],
                                "text": "Too many requests. Try again after the next sync.",
                            })
                        except (TelegramError, KeyError):
                            pass
                elif "callback_query" in update:
                    if not private_callback(bot, update["callback_query"], store,
                                            settings, summary, rows):
                        changed |= _handle_tap(bot, update["callback_query"], by_prefix, store,
                                               owners, summary, rows=rows, context=chat_state,
                                               page_size=page_size, max_items=max_items,
                                               site_url=settings.site_url)
                elif ("message" in update and
                      not private_message(bot, update["message"], store,
                                          settings, rows, summary)):
                    _handle_message(bot, update["message"], rows, store, owners,
                                    summary, page_size=page_size,
                                    max_items=max_items, site_url=settings.site_url,
                                    context=chat_state, ai_settings=settings)
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
        init_db(settings.db_path)
        with Database(settings.db_path) as db:
            state.restore_if_needed(db, settings.state_path, settings.seen_state_path)
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


def _favorite_screen(
    store: FeedbackStore, user: int, rows: list[sqlite3.Row], *, page: int = 0,
) -> tuple[str, dict[str, Any]]:
    from ..core.output_quality import application_url_issue
    from ..core.textproc import escape_telegram_html as esc, telegram_visible_length
    from .telegram import MAX_MESSAGE_CHARS, SAFETY_CHARS

    saved = store.favorites(user)
    header = f"🔖 <b>My favorites · {len(saved)}</b>"
    if not saved:
        return (header + "\n\nNothing saved yet. Tap 🔖 Save in bot on a channel post.",
                {"inline_keyboard": []})

    blocks: list[tuple[str, list[dict[str, str]], str]] = []
    for number, prefix in enumerate(saved, 1):
        matches = [row for row in rows if row["url_hash"].startswith(prefix)]
        row = matches[0] if len(matches) == 1 else None
        if row:
            text = (
                f"{number}. <b>{esc(row['title'][:120])}</b> — {esc(row['institution'][:100])}"
                + (" ⚠️ Known closed" if row["closed_at"] or row["expired_at"] else
                   " · availability unverified")
            )
        else:
            text = f"{number}. Saved position {prefix} · details pending snapshot sync"
        buttons: list[dict[str, str]] = []
        if row and application_url_issue(row["apply_url"]) is None:
            buttons.append({"text": f"↗ Open {number}", "url": row["apply_url"]})
        buttons.append({"text": f"✕ Remove {number}",
                        "callback_data": f"fav:remove:{prefix}"})
        blocks.append((text, buttons, prefix))

    # Reserve space for the repeated header, page indicator and a save notice.
    # Visible UTF-16 units, rather than raw HTML bytes, are Telegram's limit.
    budget = MAX_MESSAGE_CHARS - SAFETY_CHARS - 64
    reserve = "\n\nPage 200 of 200"
    pages: list[list[tuple[str, list[dict[str, str]], str]]] = []
    current: list[tuple[str, list[dict[str, str]], str]] = []
    for block in blocks:
        prospective = [*current, block]
        trial = header + "\n\n" + "\n\n".join(item[0] for item in prospective) + reserve
        if current and (len(current) >= 12 or telegram_visible_length(trial) > budget):
            pages.append(current)
            current = [block]
        else:
            current = prospective
    if current:
        pages.append(current)

    actual = min(max(0, page), len(pages) - 1)
    selected = pages[actual]
    keyboard: list[list[dict[str, str]]] = []
    for _, actions, _ in selected:
        buttons = [button.copy() for button in actions]
        buttons[-1]["callback_data"] += f":{actual}"
        keyboard.append(buttons)
    navigation: list[dict[str, str]] = []
    if actual:
        navigation.append({"text": "← Previous",
                           "callback_data": f"fav:page:{actual - 1}"})
    if actual + 1 < len(pages):
        navigation.append({"text": "Next →",
                           "callback_data": f"fav:page:{actual + 1}"})
    if navigation:
        keyboard.append(navigation)
    body = header + "\n\n" + "\n\n".join(item[0] for item in selected)
    if len(pages) > 1:
        body += f"\n\nPage {actual + 1} of {len(pages)}"
    return body, {"inline_keyboard": keyboard}


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
    settings = page_opts.pop('ai_settings', None)
    owner = chat in owners
    kind = command_of(msg.get("text"))
    if not kind:
        return
    text_input = (msg.get('text') or '').strip()
    private_sender = (chat is not None and chat > 0
                      and (msg.get("chat") or {}).get("type") == "private"
                      and _chat_id(msg.get("from")) == chat)
    import re
    saving = re.fullmatch(r"/start(?:@[A-Za-z0-9_]+)?\s+f_([a-f0-9]{16})", text_input)
    if chat is not None and private_sender and (saving or kind in ("favorites", "delete") or
                           (not owner and text_input.lower().split("@", 1)[0] == "/saved")):
        if saving:
            try:
                fresh = store.add_favorite(chat, saving.group(1))
                note = ("✅ Saved to your private favorites." if fresh
                        else "Already in your favorites.")
            except ValueError:
                note = "Favorites limit reached (200). Remove one first."
            body, keyboard = _favorite_screen(store, chat, rows)
            bot.send(str(chat), note + "\n\n" + body, keyboard)
        elif kind == "delete":
            bot.send(str(chat), "Delete your private favorites and active subscriptions?",
                     {"inline_keyboard": [[{"text": "Delete my data",
                       "callback_data": "fav:delete:yes"}]]})
        else:
            body, keyboard = _favorite_screen(store, chat, rows)
            bot.send(str(chat), body, keyboard)
        summary["received"] += 1
        summary["commands"] += 1
        return
    natural_question = kind == 'help' and not text_input.startswith('/') and bool(
        settings and settings.get_openrouter_keys())
    is_ai = kind in ('ask', 'forget') or natural_question
    if not owner:
        private_sender = chat is not None and chat > 0 and _chat_id(msg.get('from')) == chat
        if private_sender and text_input.lower().split('@')[0] in ('/start', '/help'):
            bot.send(str(chat), '📚 <b>Collegeum database chat</b>\n\n'
                     'Ask /ask Which economics roles close this month?\n'
                     '3 questions per minute, within a shared hourly cap. '
                     'Personal tracking stays private to the owners.')
            summary['received'] += 1
            summary['commands'] += 1
            return
        if not (private_sender and is_ai and settings and settings.telegram_ai_public_enabled):
            summary['ignored'] += 1
            return
    if is_ai and settings is not None and chat is not None:
        from .assistant import ask_database
        from .browse import menu_keyboard

        message_id = msg.get('message_id')
        request_key = f'{chat}:{message_id}'
        replies = store.data.get('assistant_replies', {})
        prior = replies.get(request_key) if isinstance(replies, dict) else None
        if isinstance(prior, dict) and prior.get('stage') in ('sent', 'uncertain'):
            if prior['stage'] == 'uncertain':
                summary['failed'] += 1
                log.warning('ai_reply_needs_verification', message_id=message_id)
            return  # Never repeat a confirmed or possibly accepted reply.

        if kind == 'forget':
            queries = store.data.get('assistant_queries', {})
            if isinstance(queries, dict):
                queries.pop(str(chat), None)
            store.mark_dirty()
            store.save()
            answer = 'Your AI follow-up context has been cleared. Rate limits still apply.'
        else:
            router = Router(load_preferences(settings.preferences_config))
            records = []
            for row in rows:
                record = state._public_record(row)
                record.update({key: row[key] for key in (
                    'url_hash', 'closed_at', 'expired_at', 'first_seen_at', 'last_seen_at',
                )})
                record['kind'] = router.kind_for_row(row)
                records.append(record)
            question = text_input if natural_question else text_input.partition(' ')[2]
            answer = ask_database(question, records, store, settings, user_id=chat, owner=owner,
                                  request_id=message_id, client=bot.client.client)
        try:
            bot.send(str(chat), answer, menu_keyboard() if owner else None)
        except TelegramError as exc:
            cached = store.data.get('assistant_replies', {}).get(request_key)
            if exc.uncertain and isinstance(cached, dict):
                cached['stage'] = 'uncertain'
                store.mark_dirty()
                store.save()
            raise
        cached = store.data.get('assistant_replies', {}).get(request_key)
        if isinstance(cached, dict):
            cached['stage'] = 'sent'
            store.mark_dirty()
            store.save()
        summary['received'] += 1
        summary['commands'] += 1
        return
    summary["received"] += 1
    if kind == "help":
        from .browse import menu_keyboard

        bot.send(str(chat), HELP, menu_keyboard())
        summary["commands"] += 1
        return
    from .browse import home, more, screen, search_token

    context = page_opts.pop('context', {})
    if kind == 'menu':
        text, keyboard = home(rows, store)
    elif kind == 'more':
        text, keyboard = more()
    else:
        query = (msg.get('text') or '').partition(' ')[2].strip()[:160] if kind == 'search' else ''
        token = search_token(query, context) if query else ''
        text, keyboard = screen(kind, rows, store, query=query, search_id=token, **page_opts)
    bot.send(str(chat), text, keyboard)
    summary["commands"] += 1


def _handle_tap(
    bot: _Bot,
    cq: dict[str, Any],
    by_prefix: dict[str, sqlite3.Row],
    store: FeedbackStore,
    owners: set[int],
    summary: dict[str, int],
    *, rows: list[sqlite3.Row] | None = None, context: dict[str, Any] | None = None,
    page_size: int = 5, max_items: int = 60, site_url: str = '',
) -> bool:
    """Returns True when public exports need refreshing, including replay recovery."""
    data = cq.get('data') or ''
    message = cq.get("message") or {}
    chat = _chat_id(message.get("chat"))
    user = _chat_id(cq.get("from"))
    if isinstance(data, str) and data.startswith("fav:"):
        parts = data.split(":")
        if (chat is None or chat <= 0 or chat != user
                or (message.get("chat") or {}).get("type") != "private"):
            summary["ignored"] += 1
            return False
        page = 0
        if parts == ["fav", "delete", "yes"]:
            if not store.callback_seen(str(cq.get("id") or "")):
                store.delete_favorites(chat)
                store.remove_subscriber(chat)
                store.remember_callback(str(cq.get("id") or ""))
                store.save()  # checkpoint deletion before an uncertain Telegram reply
        elif len(parts) in (3, 4) and parts[1] == "remove":
            import re
            if re.fullmatch(r"[a-f0-9]{16}", parts[2]) is None:
                return False
            if len(parts) == 4:
                if re.fullmatch(r"\d{1,3}", parts[3]) is None:
                    return False
                page = int(parts[3])
            if not store.callback_seen(str(cq.get("id") or "")):
                store.remove_favorite(chat, parts[2])
                store.remember_callback(str(cq.get("id") or ""))
                store.save()
        elif (len(parts) == 3 and parts[1] == "page"
              and parts[2].isascii() and parts[2].isdigit()
              and len(parts[2]) <= 3):
            page = int(parts[2])
        else:
            return False
        body, keyboard = _favorite_screen(store, chat, rows or [], page=page)
        try:
            bot.call("answerCallbackQuery", {"callback_query_id": cq["id"]})
        except (TelegramError, KeyError):
            pass
        if message.get("message_id"):
            bot.call("editMessageText", {"chat_id": chat, "message_id": message["message_id"],
                     "text": body, "parse_mode": "HTML", "reply_markup": keyboard})
        summary["taps"] += 1
        return False
    if user not in owners:
        summary["ignored"] += 1
        return False
    if isinstance(data, str) and data.startswith(('view|', 'detail|')):
        from .browse import VIEWS, details, home, menu_keyboard, more, screen, valid_prefix

        message = cq.get('message') or {}
        if _chat_id(message.get('chat')) not in owners or not message.get('message_id'):
            summary['ignored'] += 1
            return False
        try:
            bot.call('answerCallbackQuery', {'callback_query_id': cq['id']})
        except TelegramError:
            pass
        parts = data.split('|')
        if parts[0] == 'detail' and len(parts) == 2 and valid_prefix(parts[1]):
            row = by_prefix.get(parts[1])
            if row is None:
                text, keyboard = 'This position is no longer available. Try the current list.', \
                    menu_keyboard()
            else:
                text, keyboard = details(row, store)
        elif len(parts) == 3 and parts[0] == 'view' and parts[2].isascii() \
                and parts[2].isdigit() and len(parts[2]) <= 6:
            kind, page = parts[1], int(parts[2])
            query, token = '', ''
            if kind.startswith('search:'):
                token = kind.partition(':')[2]
                searches = (context or {}).get('searches', {})
                query = searches.get(token, '') if isinstance(searches, dict) else ''
                kind = 'search'
            if kind == 'menu':
                text, keyboard = home(rows or [], store)
            elif kind == 'more':
                text, keyboard = more()
            elif kind == 'help':
                text, keyboard = HELP, menu_keyboard()
            elif kind in VIEWS:
                text, keyboard = screen(kind, rows or [], store, page=page, query=query,
                                        search_id=token, page_size=page_size,
                                        max_items=max_items, site_url=site_url)
            else:
                return False
        else:
            return False
        try:
            bot.call('editMessageText', {
                'chat_id': message['chat']['id'], 'message_id': message['message_id'],
                'text': text, 'parse_mode': 'HTML', 'reply_markup': keyboard,
                'link_preview_options': {'is_disabled': True},
            })
        except TelegramError as exc:
            if not (exc.status == 400 and 'message is not modified' in str(exc).lower()):
                raise
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

