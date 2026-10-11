"""Private Telegram admin console for Collegeum's scheduled, serverless worker.

The public dashboard must never expose subscriber identifiers, callbacks,
recovery cursors, secrets or admin operations. Only the configured positive
TELEGRAM_ADMIN_CHAT_ID may access the admin menu.
"""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from typing import TYPE_CHECKING, Any

from .. import state
from ..core.db import Database, init
from ..settings import Settings

if TYPE_CHECKING:
    from .feedback import FeedbackStore

ACTIONS_URL = "https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/workflows/pipeline.yml"


def admin_id(settings: Settings) -> int | None:
    raw = settings.telegram_admin_chat_id.strip()
    return int(raw) if raw.isdecimal() and int(raw) > 0 else None


def buttons(*, paused: bool = False) -> dict[str, Any]:
    return {"inline_keyboard": [
        [
            {"text": "Overview", "callback_data": "adm:status"},
            {"text": "Runs", "callback_data": "adm:runs"},
        ],
        [
            {"text": "Delivery queue", "callback_data": "adm:queue"},
            {"text": "Cache / sources", "callback_data": "adm:cache"},
        ],
        [{"text": "▶ Resume private alerts" if paused else "⏸ Pause private alerts",
          "callback_data": "adm:resume" if paused else "adm:pause"}],
        [{"text": "Run pipeline in GitHub", "url": ACTIONS_URL}],
    ]}


def render(settings: Settings, store: FeedbackStore, page: str = "status") -> str:
    """Administrative snapshots contain counts, never identifying details."""
    if page not in {"status", "runs", "queue", "cache"}:
        page = "status"
    paused = bool(store.data.get("ops", {}).get("paused"))
    status = "Paused" if paused else "Active"
    header = f"<b>Collegeum · Admin</b>\nPrivate alerts: <b>{status}</b>"
    subs = store.subscribers
    total_uncertain = sum(
        1 for item in subs.values() for rec in item["deliveries"].values()
        if rec["state"] in ("sending", "uncertain")
    )
    if page == "status":
        return (
            f"{header}\n\n"
            f"👥 Subscribers: {len(subs)}\n"
            f"⚠️ Uncertain private sends: {total_uncertain}\n"
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

    careers = load_career(settings.career_state_path)
    recent = max((j["first_seen_at"] for j in careers), default="none")
    return (
        f"{header}\n\n<b>Storage and cache</b>\n"
        f"HTTP cache entries: {cache} ({current} replayable)\n"
        f"Previously encountered URLs: {sources}\n"
        f"Career feed records: {len(careers)}\n"
        f"Newest career record: {escape(recent[:19])}\n"
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
    store._dirty = True
