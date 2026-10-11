"""Two-phase private Telegram outbox for GitHub Actions.

The workflow MUST commit the encrypted 'sending' intents before invoking
send_batch(). A crash after remote acceptance leaves the remote journal in
'sending', which cannot be reselected automatically. This is an at-most-once
automatic delivery policy, not guaranteed delivery.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .. import state
from ..core.db import Database, init
from ..ingest.career import load_career
from ..settings import Settings
from .feedback import FeedbackStore
from .subscriptions import MAX_PER_USER, MAX_TOTAL, matching, render_alert
from .telegram import TelegramClient, TelegramError

DEFAULT_BATCH = Path("data/.private_delivery_batch.json")


def _store(settings: Settings) -> FeedbackStore:
    if not settings.feedback_encryption_key:
        raise ValueError("FEEDBACK_ENCRYPTION_KEY is required for private deliveries")
    return FeedbackStore.from_settings(settings)


def _save_batch(path: Path, batch: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dest = path.with_name(path.name + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(dest, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(batch, f, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(dest, path)
    finally:
        dest.unlink(missing_ok=True)


def plan_batch(settings: Settings, *, path: Path = DEFAULT_BATCH) -> int:
    """Stage <=24 new intents and a private batch file; send nothing yet."""
    store = _store(settings)
    if store.subscribers and not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required before reserving alerts")
    store.prune_deliveries()
    batch: list[dict[str, str]] = []
    if store.subscribers and not store.data["ops"]["paused"]:
        init(settings.db_path)
        with Database(settings.db_path) as db:
            state.restore_if_needed(db, settings.state_path, settings.seen_state_path)
            academic = list(db.published_listings())
        careers = load_career(settings.career_state_path)
        user_ids = sorted(store.subscribers)
        cursor = store.data.get("delivery_cursor", "")
        if cursor in user_ids:
            offset = user_ids.index(cursor) + 1
            user_ids = user_ids[offset:] + user_ids[:offset]
        for user_id in user_ids:
            if len(batch) >= MAX_TOTAL:
                break
            member = store.subscriber(user_id)
            if member is None or member.get("paused"):
                continue
            selected = 0
            for job in matching(member, academic, careers):
                if selected >= MAX_PER_USER or len(batch) >= MAX_TOTAL:
                    break
                if not store.reserve_delivery(int(user_id), job["key"]):
                    continue
                batch.append({
                    "chat_id": user_id, "key": job["key"],
                    "text": render_alert(job, lang=member.get("language", "en")),
                    "url": job.get("url", ""),
                })
                selected += 1
            if store.data.get("delivery_cursor") != user_id:
                store.data["delivery_cursor"] = user_id
                store.mark_dirty()
    # Never persist reservations when batch-file creation fails; that would
    # strand the listings despite no network request being attempted.
    _save_batch(path, batch)
    store.save()
    # Both files remain local until the workflow's commit barrier.
    return len(batch)


def send_batch(
    settings: Settings, *, path: Path = DEFAULT_BATCH,
    sleep: Callable[[float], None] = time.sleep,
    client: Any | None = None,
) -> dict[str, int]:
    """Send exactly the batch whose 'sending' intents were durably committed.

    No batch is reconstructed from the encrypted state: this prevents an old
    ambiguous intent from being re-sent by a later Actions run.
    """
    store = _store(settings)
    if not path.exists():
        raise FileNotFoundError(f"private delivery batch missing: {path}")
    batch = json.loads(path.read_text("utf-8"))
    if not isinstance(batch, list) or len(batch) > MAX_TOTAL:
        raise ValueError("invalid private delivery batch size")
    counts = {
        "sent": 0, "uncertain": 0, "failed": 0,
        "unsubscribed": 0, "rejected": 0, "deferred": 0,
    }
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")
    with TelegramClient(bot_token=settings.telegram_bot_token, client=client) as telegram:
        for index, row in enumerate(batch):
            if not isinstance(row, dict) or not all(
                isinstance(row.get(k), str) for k in ("chat_id", "key", "text")
            ):
                raise ValueError("invalid private delivery record")
            chat_id = str(row["chat_id"])
            if not chat_id.isdecimal() or int(chat_id) <= 0:
                raise ValueError("invalid subscriber chat ID")
            if len(row["text"].encode("utf-8")) > 4096:
                raise ValueError("oversized Telegram HTML message")
            member = store.subscriber(chat_id)
            if member is None:
                continue  # deleted subscription must never be reactivated
            if member.get("paused") or store.data["ops"]["paused"]:
                store.cancel_delivery(int(chat_id), row["key"])
                store.save()
                continue
            intent = member["deliveries"].get(row["key"])
            if not isinstance(intent, dict) or intent.get("state") != "sending":
                continue
            url = row.get("url", "")
            link = urlsplit(url) if isinstance(url, str) else urlsplit("")
            buttons = []
            if link.scheme == "https" and link.hostname and len(url) <= 1024:
                buttons.append([{"text": "🔗 Open vacancy", "url": url}])
            buttons.append([{
                "text": "⚙️ Manage alerts", "callback_data": "sub:p:home",
            }])
            stop = False
            try:
                message_id = telegram.send_message(
                    chat_id=chat_id, html=row["text"],
                    keyboard={"inline_keyboard": buttons}, sleep=sleep,
                )
            except TelegramError as exc:
                if exc.permanent and exc.status in (400, 403):
                    if exc.status == 403:
                        store.remove_subscriber(int(chat_id))
                        counts["unsubscribed"] += 1
                    else:
                        store.reject_delivery(int(chat_id), row["key"], status=400)
                        counts["rejected"] += 1
                elif exc.status == 429:
                    store.cancel_delivery(int(chat_id), row["key"])
                    counts["deferred"] += 1
                    stop = True
                else:
                    store.finish_delivery(int(chat_id), row["key"], uncertain=True)
                    counts["uncertain"] += 1
                    stop = True
            except Exception:
                store.finish_delivery(int(chat_id), row["key"], uncertain=True)
                store.save()
                raise
            else:
                store.finish_delivery(int(chat_id), row["key"], message_id=message_id)
                counts["sent"] += 1
            store.save()
            if stop:
                # None of the remaining batch entries has been submitted.
                # Release only those known-unattempted intents; never
                # release the request with an ambiguous remote outcome.
                for remainder in batch[index + 1:]:
                    pending = store.subscriber(remainder["chat_id"])
                    if pending is None:
                        continue
                    receipt = pending["deliveries"].get(remainder["key"])
                    if receipt is not None and receipt["state"] == "sending":
                        store.cancel_delivery(int(remainder["chat_id"]), remainder["key"])
                store.save()
                break
    return counts
