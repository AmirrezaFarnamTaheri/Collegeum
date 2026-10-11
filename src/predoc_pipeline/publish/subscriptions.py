"""Per-user Telegram opt-in, typed interests and crash-safe private delivery."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from html import escape
from typing import TYPE_CHECKING, Any

from ..core.timeparse import parse_datetime, utcnow
from ..routing import Router
from .telegram import TelegramClient, TelegramError

if TYPE_CHECKING:
    from .feedback import FeedbackStore

TOPIC_LABELS = {
    "predoc": "🎓 Predoc / research assistant",
    "phd": "📚 PhD positions",
    "postdoc": "🔬 Postdocs",
    "data_scientist": "🧠 Data science",
    "data_analyst": "📊 Data analyst / BI",
    "econ_consulting": "📈 Economics consulting",
    "research_analyst": "🔎 Research / economic analyst",
}
TOPICS = frozenset(TOPIC_LABELS)
CAREER_TOPICS = frozenset(
    ("data_scientist", "data_analyst", "econ_consulting", "research_analyst")
)
CAREER_SCOPES = {"iran": "🇮🇷 Iran-based jobs", "remote": "🌍 Worldwide-remote jobs"}
MAX_PER_USER = 4
MAX_TOTAL = 24


def private_user_id(message: dict[str, Any]) -> int | None:
    """Verify Telegram's sender is the same person as the private chat."""
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    try:
        if chat.get("type") != "private":
            return None
        chat_id = int(chat.get("id"))
        if chat_id > 0 and int(sender.get("id")) == chat_id:
            return chat_id
    except (TypeError, ValueError):
        pass
    return None


def menu(member: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    topics = member.get("topics", {}) if member else {}
    scopes = member.get("scopes", {}) if member else {}
    lines = [
        "<b>Collegeum · Your alerts</b>",
        "Choose interests below. Your choices apply only to your private chat.",
        "Alerts start from the time you opt in. /latest previews matched jobs.",
        "",
        "<b>Roles</b>",
    ]
    buttons: list[list[dict[str, str]]] = []
    for key, label in TOPIC_LABELS.items():
        active = key in topics
        lines.append(f"{'✅' if active else '▫️'} {escape(label)}")
        buttons.append([{
            "text": f"{'✅' if active else '▫️'} {label}",
            "callback_data": f"sub:t:{key}",
        }])
    lines += ["", "<b>Job markets</b>"]
    for key, label in CAREER_SCOPES.items():
        active = key in scopes
        lines.append(f"{'✅' if active else '▫️'} {escape(label)}")
        buttons.append([{
            "text": f"{'✅' if active else '▫️'} {label}",
            "callback_data": f"sub:g:{key}",
        }])
    lines += [
        "", "Job markets are independent: Iran-based ≠ globally remote.",
        "Remote alerts include only roles explicitly available worldwide/Iran.",
        "Use /stop to unsubscribe and erase your delivery history.",
    ]
    return "\n".join(lines), {"inline_keyboard": buttons}


def parse_toggle(raw: str | None) -> tuple[str, str] | None:
    if not raw or len(raw.encode("utf-8")) > 64:
        return None
    parts = raw.split(":")
    if len(parts) != 3 or parts[0] != "sub":
        return None
    kind = {"t": "topics", "g": "scopes"}.get(parts[1])
    if kind and parts[2] in (TOPICS if kind == "topics" else CAREER_SCOPES):
        return kind, parts[2]
    return None


def _instant(value: str) -> datetime | None:
    try:
        value_dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value_dt.replace(tzinfo=UTC) if value_dt.tzinfo is None else value_dt.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def eligible(member: dict[str, Any], category: str, scope: str,
             published_at: str) -> bool:
    """A new selection never backfills old jobs or another user's interests."""
    choice_at = _instant(member.get("topics", {}).get(category, ""))
    posted_at = _instant(published_at)
    if choice_at is None or posted_at is None:
        return False
    if scope:
        scope_at = _instant(member.get("scopes", {}).get(scope, ""))
        if scope_at is None:
            return False
        choice_at = max(choice_at, scope_at)
    return posted_at >= choice_at


def matching(member: dict[str, Any], academic: list[sqlite3.Row],
             careers: list[dict[str, str]]) -> list[dict[str, str]]:
    """Select recent published academic positions and explicit-market career jobs."""
    cutoff = datetime.now(UTC) - timedelta(days=14)
    jobs: list[dict[str, str]] = []
    for row in academic:
        if row["status"] != "published" or row["closed_at"] or row["expired_at"]:
            continue
        deadline = parse_datetime(row["deadline"])
        if deadline and deadline < utcnow():
            continue
        when = str(row["published_at"] or "")
        parsed = _instant(when)
        kind = Router.position_kind(row["title"], row["summary"] or "")
        if parsed is None or parsed < cutoff or not eligible(member, kind, "", when):
            continue
        jobs.append({
            "key": "academic:" + row["url_hash"], "category": kind,
            "title": row["title"], "employer": row["institution"],
            "location": ", ".join(x for x in (row["city"], row["country"]) if x),
            "scope": "", "first_seen_at": when, "source": "Collegeum",
            "url": row["apply_url"],
        })
    for job in careers:
        when = job["first_seen_at"]
        parsed = _instant(when)
        if parsed and parsed >= cutoff and eligible(
            member, job["category"], job["scope"], when,
        ):
            jobs.append(job)
    jobs.sort(key=lambda item: (item["first_seen_at"], item["key"]), reverse=True)
    return jobs


def render_alert(job: dict[str, str]) -> str:
    parts = [
        f"<b>{escape(TOPIC_LABELS.get(job['category'], 'Opportunity'))}</b>",
        f"<b>{escape(job['title'][:175])}</b>",
        f"🏢 {escape(job['employer'][:140])}",
        f"📍 {escape(job.get('location') or 'Location not specified')}",
        f"📌 {escape(CAREER_SCOPES.get(job['scope'], 'Academic'))}",
        f"via {escape(job.get('source', 'Collegeum'))}",
        f'<a href="{escape(job["url"], quote=True)}">View opportunity</a>',
    ]
    return "\n".join(parts)


def dispatch(store: FeedbackStore, telegram: TelegramClient,
             academic: list[sqlite3.Row], careers: list[dict[str, str]],
             *, per_user: int = MAX_PER_USER, total: int = MAX_TOTAL,
             sleep: Any = None) -> dict[str, int]:
    """Enqueue before network IO. An ambiguous request is never replayed."""
    counters = {"sent": 0, "uncertain": 0, "failed": 0}
    if not store.key or not store.subscribers:
        return counters
    if store.data.get("ops", {}).get("paused"):
        return counters
    options: dict[str, Any] = {"sleep": sleep} if sleep is not None else {}
    ids = sorted(store.subscribers)
    cursor = store.data.get("delivery_cursor", "")
    if cursor in ids:
        pivot = ids.index(cursor) + 1
        ids = ids[pivot:] + ids[:pivot]
    for identifier in ids:
        if sum(counters.values()) >= total:
            break
        chat_id = int(identifier)
        member = store.subscriber(chat_id)
        if member is None:
            continue
        attempted = 0
        for job in matching(member, academic, careers):
            if attempted >= per_user or sum(counters.values()) >= total:
                break
            key = job["key"]
            if not store.reserve_delivery(chat_id, key):
                continue
            # Persist the send intent before the remote request. If this fails
            # no network request occurs, and the update cursor is unchanged.
            store.save()
            attempted += 1
            try:
                message_id = telegram.send_message(
                    chat_id=identifier, html=render_alert(job), **options,
                )
            except TelegramError as exc:
                if exc.permanent and exc.status in (400, 403):
                    # Telegram explicitly refused creation of this message.
                    store.cancel_delivery(chat_id, key)
                    if exc.status == 403:
                        store.remove_subscriber(chat_id)
                    store.save()
                    counters["failed"] += 1
                    break
                if exc.status == 429:
                    store.cancel_delivery(chat_id, key)
                    store.save()
                    counters["failed"] += 1
                    break
                store.finish_delivery(chat_id, key, uncertain=True)
                store.save()
                counters["uncertain"] += 1
                break
            except Exception:
                store.finish_delivery(chat_id, key, uncertain=True)
                store.save()
                counters["uncertain"] += 1
                raise
            store.finish_delivery(chat_id, key, message_id=message_id)
            store.save()
            counters["sent"] += 1
        store.data["delivery_cursor"] = identifier
        store._dirty = True
        store.save()
    return counters
