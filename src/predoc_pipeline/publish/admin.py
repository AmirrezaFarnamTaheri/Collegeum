"""Private Telegram admin console for Collegeum's scheduled, serverless worker.

The public dashboard must never expose subscriber identifiers, callbacks,
recovery cursors, secrets or admin operations. Only the configured positive
TELEGRAM_ADMIN_CHAT_ID may access the admin menu.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import state
from ..core.db import Database, init
from ..settings import Settings

if TYPE_CHECKING:
    from .feedback import FeedbackStore

def _actions_url() -> str:
    """Use the current repository instead of a stale name after a rename."""
    import os
    import re

    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        repository = "AmirrezaFarnamTaheri/Collegeum"
    return f"https://github.com/{repository}/actions/workflows/pipeline.yml"


ACTIONS_URL = _actions_url()


def admin_id(settings: Settings) -> int | None:
    raw = settings.telegram_admin_chat_id.strip()
    return int(raw) if raw.isascii() and raw.isdecimal() and int(raw) > 0 else None


def buttons(*, paused: bool = False, page: str = "status") -> dict[str, Any]:
    def nav(label: str, target: str) -> dict[str, str]:
        prefix = "● " if page == target else ""
        return {"text": prefix + label, "callback_data": f"adm:{target}"}

    return {"inline_keyboard": [
        [nav("Overview", "status"), nav("Recent runs", "runs")],
        [nav("Delivery queue", "queue"), nav("Sources & cache", "cache")],
        [nav("Recovery cases", "recovery")],
        [{"text": "↻ Refresh this view", "callback_data": f"adm:{page}"}],
        [{"text": "▶ Resume private alerts" if paused else "⏸ Pause private alerts",
          "callback_data": "adm:resume" if paused else "adm:pause"}],
        [{"text": "↗ Open scheduled pipeline", "url": ACTIONS_URL}],
    ]}


def render(settings: Settings, store: FeedbackStore, page: str = "status") -> str:
    """Administrative snapshots contain counts, never identifying details."""
    if page not in {"status", "runs", "queue", "cache", "recovery"}:
        page = "status"
    paused = bool(store.data.get("ops", {}).get("paused"))
    status = "Paused" if paused else "Active"
    header = f"<b>Collegeum · Admin</b>\nPrivate alerts: <b>{status}</b>"
    subs = store.subscribers
    active_subscribers = sum(1 for member in subs.values() if member["topics"])
    paused_subscribers = sum(1 for member in subs.values() if member.get("paused"))
    total_uncertain = sum(
        1 for item in subs.values() for rec in item["deliveries"].values()
        if rec["state"] in ("sending", "uncertain")
    )
    total_rejected = sum(
        1 for item in subs.values() for rec in item["deliveries"].values()
        if rec["state"] == "rejected"
    )
    if page == "recovery":
        records = [
            (chat_id, key, data)
            for chat_id, member in subs.items()
            for key, data in member["deliveries"].items()
            if data["state"] in ("sending", "uncertain", "rejected")
        ]
        records.sort(key=lambda entry: (entry[2].get("at", ""), entry[0], entry[1]))
        shown = records[:6]
        rows = [
            f"{index}. chat={escape(chat_id)} "
            f"key=<code>{escape(key[:220])}</code> "
            f"({escape(str(rec['state']))})"
            for index, (chat_id, key, rec) in enumerate(shown, 1)
        ]
        return (
            f"{header}\n\n<b>Private delivery recovery</b>\n"
            + ("\n".join(rows) if rows else "No unresolved private deliveries.")
            + (f"\n…plus {len(records) - len(shown)} more" if len(records) > len(shown) else "")
            + "\n\nVerify the destination chat independently first. "
            "After proof of arrival, send /reconcile CHAT_ID KEY sent MESSAGE_ID. "
            "After proof of absence, send /reconcile CHAT_ID KEY absent "
            "CONFIRM_NOT_DELIVERED. These commands are admin-only; no uncertain "
            "delivery is replayed without explicit verification."
        )
    if page == "status":
        return (
            f"{header}\n\n"
            f"👥 Active subscriptions: {active_subscribers}\n"
            f"⏸ Individually paused: {paused_subscribers}\n"
            f"⚠️ Uncertain private sends: {total_uncertain}\n"
            f"⛔ Rejected private sends: {total_rejected}\n"
            "⏱ Pipeline: every 4 hours · Telegram sync: ~30 minutes\n"
            "⚙️ Publication scheduling and retry are managed in GitHub Actions.\n"
            "Pause affects private alerts only, not public channel or ingestion."
        )
    init(settings.db_path)
    with Database(settings.db_path) as db:
        state.restore_if_needed(db, settings.state_path, settings.seen_state_path)
        state.restore_runs(db, settings.health_json)
        if page == "runs":
            runs = db.recent_runs(8)
            lines = [
                f"{r['started_at'][:16]} · {r['outcome']} · "
                f"new {r['published']} · issues {r['errors']}"
                for r in runs
            ]
            return header + "\n\n<b>Recent pipeline runs</b>\n" + (
                "\n".join(escape(line) for line in lines) if lines else "No runs recorded."
            )
        if page == "queue":
            pending = db.conn.execute(
                "SELECT COUNT(*) FROM listings WHERE status IN ('pending','unpublished')"
            ).fetchone()[0]
            unsure = db.conn.execute(
                "SELECT COUNT(*) FROM listings WHERE status='delivery-uncertain'"
            ).fetchone()[0]
            dlq = db.conn.execute("SELECT COUNT(*) FROM dlq").fetchone()[0]
            return (
                f"{header}\n\n<b>Delivery and recovery</b>\n"
                f"Pending academic publications: {pending}\n"
                f"Uncertain channel sends: {unsure}\n"
                f"Uncertain private sends: {total_uncertain}\n"
                f"Rejected private sends: {total_rejected}\n"
                f"Dead-letter events: {dlq}\n"
                "Uncertain deliveries require verification in Telegram "
                "before any manual retry."
            )
        cache = db.conn.execute("SELECT COUNT(*) FROM http_cache").fetchone()[0]
        current = db.conn.execute(
            "SELECT COUNT(*) FROM http_cache WHERE body IS NOT NULL"
        ).fetchone()[0]
        sources = db.conn.execute("SELECT COUNT(*) FROM seen_items").fetchone()[0]
    from ..ingest.career import load_career

    try:
        careers = load_career(settings.career_state_path)
    except (OSError, UnicodeError, ValueError):
        careers = []
        journal_status = "Career journal unreadable; collection needs attention."
    else:
        journal_status = ""
    recent = max((j["first_seen_at"] for j in careers), default="none")
    source_health = "No career-source checks recorded."
    health_path = Path(settings.career_health_path)
    if health_path.exists():
        try:
            data = json.loads(health_path.read_text(encoding="utf-8"))
            checks = data["sources"]
            display_names = {
                "jobicy": "Jobicy · worldwide remote",
                "jobinja": "Jobinja · Iran",
                "irantalent": "IranTalent · Iran",
            }
            check_lines = [
                f"• {display_names.get(name, name)}: "
                f"{info['accepted']} matches / {info['fetched']} requests"
                for name, info in checks.items() if info.get("requested")
            ]
            source_health = (
                f"Checked {str(data['checked_at'])[:19]} UTC\n"
                + ("\n".join(check_lines) if check_lines else "No career feeds requested.")
                + f"\nFeed errors: {len(data.get('errors', []))}"
            )
            if data.get("errors"):
                details = "; ".join(str(e)[:90] for e in data["errors"][:2])
                source_health += f"\nLatest issues: {details}"
        except (ValueError, KeyError, TypeError):
            source_health = "Career-source health record is invalid."
    return (
        f"{header}\n\n<b>Storage and cache</b>\n"
        f"HTTP cache entries: {cache} ({current} replayable)\n"
        f"Previously encountered URLs: {sources}\n"
        f"Career feed records: {len(careers)}\n"
        f"Newest career record: {escape(recent[:19])}\n"
        f"{escape(journal_status)}\n"
        f"{escape(source_health)}\n"
        "Runtime HTTP cache is ephemeral on CI; durable journals prevent "
        "repeat private notifications across scheduled runs."
    )


def audit(store: FeedbackStore, actor: int, action: str) -> None:
    if action not in {"pause", "resume"}:
        raise ValueError("invalid admin action")
    ops = store.data.setdefault("ops", {"paused": False, "audit": []})
    ops["paused"] = action == "pause"
    records = ops.setdefault("audit", [])
    records.append({"at": datetime.now(UTC).isoformat(), "actor": actor, "action": action})
    del records[:-100]
    store.mark_dirty()
