"""Per-user Telegram opt-in, typed interests and crash-safe private delivery."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any

from ..core.output_quality import (
    application_url_issue,
    authentication_page_text,
    excluded_by_audit,
)
from ..core.timeparse import parse_datetime, utcnow
from ..routing import Router

TOPIC_LABELS = {
    "predoc": "🎓 Predoc / research assistant",
    "phd": "📚 PhD positions",
    "life_sciences_phd": "🧬 Life Sciences PhD · Europe",
    "postdoc": "🔬 Postdocs",
    "research": "🔎 Research staff (PhD-qualified)",
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
        chat_value, sender_value = chat.get("id"), sender.get("id")
        if (not isinstance(chat_value, (str, int))
                or not isinstance(sender_value, (str, int))
                or isinstance(chat_value, bool) or isinstance(sender_value, bool)):
            return None
        chat_id = int(chat_value)
        if chat_id > 0 and int(sender_value) == chat_id:
            return chat_id
    except ValueError:
        pass
    return None


def menu(
    member: dict[str, Any] | None, page: str = "home",
) -> tuple[str, dict[str, Any]]:
    """Compatibility entrypoint for the native Telegram UI renderer."""
    from .ui import menu as render_menu

    return render_menu(member, page)


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


def selected(member: dict[str, Any], category: str, scope: str) -> bool:
    """Preview still enforces selected topics/markets, just not the opt-in date."""
    return category in member.get("topics", {}) and (
        not scope or scope in member.get("scopes", {})
    )


def matching(member: dict[str, Any], academic: list[sqlite3.Row],
             careers: list[dict[str, str]], *, preview: bool = False,
             ) -> list[dict[str, str]]:
    """Select recent published academic positions and explicit-market career jobs."""
    cutoff = datetime.now(UTC) - timedelta(days=14)
    jobs: list[dict[str, str]] = []
    for row in academic:
        if row["status"] != "published" or row["closed_at"] or row["expired_at"]:
            continue
        # Do not privately send a record quarantined from public publication.
        if (excluded_by_audit(row["url_hash"])
                or application_url_issue(row["apply_url"]) is not None
                or authentication_page_text(row["summary"])):
            continue
        deadline = parse_datetime(row["deadline"])
        if deadline and deadline < utcnow():
            continue
        when = str(row["published_at"] or "")
        parsed = _instant(when)
        kind = Router.kind_for_row(row)
        if parsed is None or parsed < cutoff or not selected(member, kind, ""):
            continue
        if not preview and not eligible(member, kind, "", when):
            continue
        jobs.append({
            "key": "academic:" + row["url_hash"], "category": kind,
            "title": row["title"], "employer": row["institution"],
            "location": ", ".join(x for x in (row["city"], row["country"]) if x),
            "scope": "", "first_seen_at": when, "source": "Collegeum",
            "url": row["apply_url"],
        })
    for job in careers:
        if job.get("availability") == "closed":
            continue
        when = job["first_seen_at"]
        parsed = _instant(when)
        if (parsed and parsed >= cutoff and
                selected(member, job["category"], job["scope"]) and
                (preview or eligible(member, job["category"], job["scope"], when))):
            jobs.append(job)
    jobs.sort(key=lambda item: (
        _instant(item["first_seen_at"]) or datetime.min.replace(tzinfo=UTC),
        item.get("research_priority") == "focus",
        item["key"],
    ), reverse=True)
    return jobs


def render_alert(job: dict[str, str], lang: str = "en") -> str:
    """Format a safe, localized HTML notification with optional verified link."""
    from urllib.parse import urlsplit

    fa = lang == "fa"
    category = TOPIC_LABELS.get(job["category"], "Opportunity")
    if fa:
        category = {
            "predoc": "پیشادکتری / دستیار پژوهشی",
            "phd": "فرصت دکتری", "postdoc": "پسادکتری",
            "research": "پژوهشگر حرفه‌ای (دارای دکتری)",
            "life_sciences_phd": "دکتری علوم زیستی · اروپا",
            "data_scientist": "دانشمند داده",
            "data_analyst": "تحلیلگر داده",
            "econ_consulting": "مشاوره اقتصادی",
            "research_analyst": "تحلیلگر پژوهش",
        }.get(job["category"], "فرصت شغلی")
    location = job.get("location") or ("مکان نامشخص" if fa else "Location not specified")
    scope = (
        ("دورکاری جهانی" if job["scope"] == "remote" else "داخل ایران")
        if fa and job.get("scope") else
        ("دانشگاهی" if fa else CAREER_SCOPES.get(job.get("scope", ""), "Academic"))
    )
    parts = [
        f"<b>{escape(category)}</b>",
        f"<b>{escape(job['title'][:175])}</b>",
        f"🏢 {escape(job['employer'][:140])}",
        f"📍 {escape(location[:130])}",
        f"📌 {escape(scope)}",
        ("منبع: " if fa else "via ") + escape(job.get("source", "Collegeum")[:60]),
    ]
    url = job.get("url", "")
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme == "https" and bool(parsed.hostname) and (
            len(url) <= 1024
        )
    except ValueError:
        valid = False
    if job["category"] == "life_sciences_phd":
        if job.get("research_priority") == "focus":
            parts.append("🎯 " + (
                "مطالعهٔ بسیار مرتبط با علایق پژوهشی" if fa
                else "Priority research-interest match"
            ))
        parts.append("ℹ️ " + (
            "تأمین مالی، حقوق و شهریه تأیید نشده‌اند."
            if fa else "Funding, salary and tuition are not verified."
        ))
    if valid:
        parts.append(
            f'<a href="{escape(url, quote=True)}">'
            + ("مشاهده فرصت" if fa else "View opportunity") + "</a>"
        )
    return "\n".join(parts)


 

