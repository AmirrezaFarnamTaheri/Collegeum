"""Crash-safe private notification planner and message delivery.

A single digest message may acknowledge several individual job keys, but all
intents must be checkpointed before any remote Telegram request.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .. import state
from ..core.db import Database, init
from ..core.textproc import telegram_visible_length
from ..ingest.career import load_career
from ..settings import Settings
from .feedback import FeedbackStore
from .subscriptions import MAX_PER_USER, MAX_TOTAL, matching, render_alert
from .telegram import TelegramClient, TelegramError

DEFAULT_BATCH = Path("data/.private_delivery_batch.json")
MAX_DIGEST_ITEMS = 4
MESSAGE_BUDGET = 4032


def _store(settings: Settings) -> FeedbackStore:
    if not settings.feedback_encryption_key:
        raise ValueError("FEEDBACK_ENCRYPTION_KEY is required for private deliveries")
    return FeedbackStore.from_settings(settings)


def _save_batch(path: Path, batch: list[dict[str, Any]]) -> None:
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


def _local_time(member: dict[str, Any], now: datetime) -> datetime:
    try:
        zone = ZoneInfo(member.get("timezone", "UTC"))
    except (KeyError, ValueError, ZoneInfoNotFoundError):
        zone = ZoneInfo("UTC")
    return now.astimezone(zone)


def _used_today(member: dict[str, Any], now: datetime) -> int:
    local_day = _local_time(member, now).date()
    used = 0
    for receipt in member["deliveries"].values():
        if receipt["state"] not in ("sent", "sending", "uncertain"):
            continue
        try:
            at = datetime.fromisoformat(receipt["at"].replace("Z", "+00:00"))
            if at.tzinfo is None:
                at = at.replace(tzinfo=UTC)
            if _local_time(member, at).date() == local_day:
                used += 1
        except (TypeError, ValueError):
            used += 1  # unknown receipt must not bypass the daily quota
    return used


def _digest_text(jobs: list[dict[str, str]], lang: str) -> str:
    head = ("📬 <b>خلاصه روزانه فرصت‌ها</b>\n\n"
            if lang == "fa" else "📬 <b>Your daily Collegeum matches</b>\n\n")
    cards = [
        f"<b>{i}.</b>\n{render_alert(job, lang=lang)}"
        for i, job in enumerate(jobs, 1)
    ]
    return head + "\n\n────────\n\n".join(cards)


def plan_batch(
    settings: Settings, *, path: Path = DEFAULT_BATCH, now: datetime | None = None,
) -> int:
    """Reserve bounded private alerts; write no remote messages before checkpoint."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    store = _store(settings)
    if store.subscribers and not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required before reserving alerts")
    store.prune_deliveries()
    batch: list[dict[str, Any]] = []
    if store.subscribers and not store.data["ops"]["paused"]:
        init(settings.db_path)
        with Database(settings.db_path) as db:
            state.restore_if_needed(db, settings.state_path, settings.seen_state_path)
            academic = list(db.published_listings())
        careers = load_career(settings.career_state_path, tolerant=True)
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
            local = _local_time(member, current)
            if member.get("quiet_hours") and (local.hour >= 22 or local.hour < 8):
                continue
            quota = member.get("daily_limit", 6) - _used_today(member, current)
            if quota <= 0:
                continue
            candidates = [
                job for job in matching(member, academic, careers)
                if job["key"] not in member["deliveries"]
            ]
            if member.get("delivery_mode") == "digest":
                today = local.date().isoformat()
                if local.hour < 9 or member.get("digest_day") == today:
                    continue
                selected: list[dict[str, str]] = []
                lang = member.get("language", "en")
                for job in candidates:
                    if len(selected) >= min(quota, MAX_DIGEST_ITEMS):
                        break
                    trial = [*selected, job]
                    if telegram_visible_length(_digest_text(trial, lang)) > MESSAGE_BUDGET:
                        break
                    selected.append(job)
                if selected:
                    keys = [job["key"] for job in selected]
                    for key in keys:
                        if not store.reserve_delivery(int(user_id), key):
                            raise ValueError("digest reservation changed unexpectedly")
                    batch.append({
                        "chat_id": user_id, "key": keys[0], "keys": keys,
                        "text": _digest_text(selected, lang), "url": "",
                        "digest_day": today,
                    })
                    member["digest_day"] = today
                    store.mark_dirty()
            else:
                sent = 0
                for job in candidates:
                    if sent >= min(quota, MAX_PER_USER) or len(batch) >= MAX_TOTAL:
                        break
                    text = render_alert(job, lang=member.get("language", "en"))
                    if telegram_visible_length(text) > MESSAGE_BUDGET:
                        continue
                    if not store.reserve_delivery(int(user_id), job["key"]):
                        continue
                    batch.append({
                        "chat_id": user_id, "key": job["key"],
                        "text": text, "url": job.get("url", ""),
                    })
                    sent += 1
            if store.data.get("delivery_cursor") != user_id:
                store.data["delivery_cursor"] = user_id
                store.mark_dirty()
    _save_batch(path, batch)
    store.save()
    return len(batch)


def _keys(row: dict[str, Any]) -> list[str]:
    keys = row.get("keys", [row["key"]])
    if (not isinstance(keys, list) or not 1 <= len(keys) <= MAX_DIGEST_ITEMS
            or not all(isinstance(key, str) and 1 <= len(key) <= 256 for key in keys)
            or len(keys) != len(set(keys)) or keys[0] != row["key"]):
        raise ValueError("invalid private delivery keys")
    return keys


def send_batch(
    settings: Settings, *, path: Path = DEFAULT_BATCH,
    sleep: Callable[[float], None] = time.sleep,
    client: Any | None = None,
) -> dict[str, int]:
    """Submit checkpointed messages; never automatically replay uncertain outcomes."""
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
            chat_id = row["chat_id"]
            if not chat_id.isascii() or not chat_id.isdecimal() or int(chat_id) <= 0:
                raise ValueError("invalid subscriber chat ID")
            keys = _keys(row)
            member = store.subscriber(chat_id)
            if member is None:
                continue
            active = all(
                isinstance(member["deliveries"].get(key), dict)
                and member["deliveries"][key].get("state") == "sending"
                for key in keys
            )
            if not active or member.get("paused") or store.data["ops"]["paused"]:
                for key in keys:
                    if member["deliveries"].get(key, {}).get("state") == "sending":
                        store.cancel_delivery(int(chat_id), key)
                store.save()
                continue
            if telegram_visible_length(row["text"]) > MESSAGE_BUDGET:
                for key in keys:
                    store.reject_delivery(int(chat_id), key, status=400)
                counts["rejected"] += len(keys)
                store.save()
                continue
            url = row.get("url", "")
            try:
                link = urlsplit(url) if isinstance(url, str) else urlsplit("")
            except ValueError:
                link = urlsplit("")
            buttons = []
            if link.scheme == "https" and link.hostname and len(url) <= 1024:
                label = "🔗 مشاهده آگهی" if member.get("language") == "fa" else "🔗 Open vacancy"
                buttons.append([{"text": label, "url": url}])
            manage = "⚙️ مدیریت اعلان‌ها" if member.get("language") == "fa" else "⚙️ Manage alerts"
            buttons.append([{"text": manage, "callback_data": "sub:p:home"}])
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
                        for key in keys:
                            store.reject_delivery(int(chat_id), key, status=400)
                        counts["rejected"] += len(keys)
                elif exc.status == 429:
                    for key in keys:
                        store.cancel_delivery(int(chat_id), key)
                    if row.get("digest_day") == member.get("digest_day"):
                        member["digest_day"] = ""
                        store.mark_dirty()
                    counts["deferred"] += len(keys)
                    stop = True
                else:
                    for key in keys:
                        store.finish_delivery(int(chat_id), key, uncertain=True)
                    counts["uncertain"] += len(keys)
                    stop = True
            except Exception:
                for key in keys:
                    store.finish_delivery(int(chat_id), key, uncertain=True)
                store.save()
                raise
            else:
                for key in keys:
                    store.finish_delivery(int(chat_id), key, message_id=message_id)
                counts["sent"] += len(keys)
            store.save()
            if stop:
                for remainder in batch[index + 1:]:
                    pending = store.subscriber(remainder["chat_id"])
                    if pending is None:
                        continue
                    for key in _keys(remainder):
                        receipt = pending["deliveries"].get(key)
                        if receipt is not None and receipt["state"] == "sending":
                            store.cancel_delivery(int(remainder["chat_id"]), key)
                    if remainder.get("digest_day") == pending.get("digest_day"):
                        pending["digest_day"] = ""
                        store.mark_dirty()
                store.save()
                break
    return counts
