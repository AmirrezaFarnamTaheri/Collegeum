"""Committed state, dashboard payloads and the public RSS feed.

Why the SQLite file is *not* what gets committed
-----------------------------------------------
The reviewed architecture commits ``data/predocs.db`` on every run and claims
"Git easily handles binary diffs of this size". It does not. Git stores a whole
new compressed blob for each version of a binary file; it cannot usefully delta
SQLite pages, which move whenever the b-tree rebalances or ``VACUUM`` runs. A
5 MB database committed daily adds on the order of a gigabyte a year to the
repository, and every ``actions/checkout`` pays for it. Worse, two runs that
overlap produce a binary merge conflict no one can resolve.

So the committed artefact is ``data/listings.ndjson``: one JSON object per
line, append-then-rewrite, sorted by first-seen. It diffs, it compresses, it
merges by union, and it can be read by anything. The SQLite database is a
derived cache -- gitignored, rebuilt from the journal when absent. That also
makes the whole history auditable in ``git log -p``, which the binary never was.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core.timeparse import format_ts, parse_datetime, utcnow

__all__ = [
    "write_journal",
    "write_seen",
    "read_journal",
    "restore_if_needed",
    "restore_runs",
    "export_dashboard",
    "export_health",
    "export_feed",
]


# --------------------------------------------------------------------------
# Journal
# --------------------------------------------------------------------------

def write_journal(db: Any, path: str | Path) -> int:
    """Rewrite the journal from the database. Returns the record count.

    A full rewrite rather than an append: it is a few hundred kilobytes, it
    keeps the file canonically sorted so diffs stay minimal, and it means a
    half-written line from a killed process cannot corrupt the record.
    """
    records = db.export_rows()
    records.sort(key=lambda r: (r.get("first_seen_at") or "", r.get("url_hash") or ""))
    _write_lines(records, path)  # atomic on POSIX
    return len(records)


def read_journal(path: str | Path) -> list[dict[str, Any]]:
    """Read the journal, skipping malformed lines rather than failing."""
    file = Path(path)
    if not file.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            out.append(record)
    return out


def _write_lines(records: list[dict[str, Any]], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(target)


def write_seen(db: Any, path: str | Path) -> int:
    """Rewrite data/seen.ndjson: every posting URL already judged, and the verdict.

    The SQLite file is not committed, so without this every CI run would start
    with an empty ``seen_items`` table, re-read every job page and (with Gemini)
    re-spend the model quota on postings it judged yesterday.
    """
    records = db.export_seen()
    _write_lines(records, path)
    return len(records)


def restore_if_needed(db: Any, path: str | Path, seen_path: str | Path | None = None) -> int:
    """Rebuild an empty database from the committed journal.

    This is what makes the derived-cache model safe: a fresh clone, a cleared
    runner, or a corrupted file all recover by replaying the journal.
    """
    restored = 0
    if seen_path and db.seen_count() == 0:
        seen = read_journal(seen_path)
        if seen:
            db.import_seen(seen)
    if db.counts()["listings"] > 0:
        return 0
    records = read_journal(path)
    if records:
        restored = db.import_rows(records)
    return restored


def restore_runs(db: Any, health_path: str | Path) -> int:
    """Rebuild the run log from docs/data/health.json when the database is fresh."""
    if db.counts()["runs"] > 1:  # the current run is already in there
        return 0
    file = Path(health_path)
    if not file.exists():
        return 0
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except ValueError:
        return 0
    runs = [r for r in payload.get("runs", []) if r.get("finished_at")]
    return db.import_runs(runs) if runs else 0


# --------------------------------------------------------------------------
# Dashboard payloads
# --------------------------------------------------------------------------

def _row_value(row: Any, key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _public_record(row: Any) -> dict[str, Any]:
    get = row.__getitem__ if hasattr(row, "keys") else row.get
    deadline = get("deadline")
    parsed = parse_datetime(deadline)
    days_left = (parsed - utcnow()).days if parsed else None
    return {
        "id": int(get("id")),
        "title": get("title"),
        "institution": get("institution"),
        "principal_investigator": get("principal_investigator"),
        "country": get("country") or "",
        "city": get("city"),
        "is_remote": bool(get("is_remote")),
        "duration_years": get("duration_years"),
        "deadline": deadline,
        "days_left": days_left,
        "disciplines": json.loads(get("disciplines") or "[]"),
        "visa": get("visa_sponsorship_status"),
        "summary": get("summary") or "",
        "language": get("language") or "en",
        "apply_url": get("apply_url"),
        "source_url": get("source_url"),
        "confidence": round(float(get("confidence") or 0), 3),
        "first_seen_at": get("first_seen_at"),
        "deadline_note": _row_value(row, "deadline_note"),
        "visa_note": _row_value(row, "visa_note"),
        "alternate_sources": json.loads(get("alternate_sources") or "[]"),
    }


def export_dashboard(db: Any, path: str | Path, *, hidden: set[str] | None = None) -> int:
    """Write the JSON snapshot the static dashboard fetches.

    ``hidden`` holds the url_hash of positions marked ❌ in Telegram.
    """
    hidden = hidden or set()
    records = [
        _public_record(row) for row in db.active_listings() if row["url_hash"] not in hidden
    ]
    payload = {
        "generated_at": format_ts(),
        "count": len(records),
        "listings": records,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return len(records)


def export_health(db: Any, path: str | Path, *, stats: dict[str, Any]) -> None:
    """Write run history and per-source yield, so failures are visible.

    A dashboard that only shows listings cannot distinguish "a quiet week" from
    "every scraper has been broken since the portal redesign". This file is
    what makes that difference legible without reading workflow logs.
    """
    runs = []
    for row in db.recent_runs(limit=30):
        try:
            source_stats = json.loads(row["source_stats"] or "{}")
        except ValueError:
            source_stats = {}
        runs.append(
            {
                "source_stats": {
                    name: {k: v for k, v in data.items() if k != "messages"}
                    for name, data in source_stats.items()
                    if isinstance(data, dict)
                },
                "run_id": row["run_id"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "ingested": row["ingested"],
                "gated": row["gated"],
                "extracted": row["extracted"],
                "duplicates": row["duplicates"],
                "published": row["published"],
                "errors": row["errors"],
                "llm_calls": row["llm_calls"],
                "outcome": row["outcome"],
            }
        )
    payload = {
        "generated_at": format_ts(),
        "counts": db.counts(),
        "last_run": stats,
        "runs": runs,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------
# Public RSS
# --------------------------------------------------------------------------

_RSS_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}


def _xml_escape(value: str) -> str:
    return "".join(_RSS_ESCAPES.get(c, c) for c in str(value or ""))


def export_feed(
    db: Any,
    path: str | Path,
    *,
    site_url: str = "",
    limit: int = 100,
    hidden: set[str] | None = None,
) -> int:
    """Publish the channel as RSS as well.

    Costs about forty lines and removes Telegram as a single point of access:
    anyone can subscribe in a reader, and the data stays usable if the bot
    token is ever revoked.
    """
    hidden = hidden or set()
    rows = [r for r in db.active_listings() if r["url_hash"] not in hidden][:limit]
    now = utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        "<title>Predoc listings (non-US)</title>",
        f"<link>{_xml_escape(site_url or 'https://example.invalid')}</link>",
        "<description>Pre-doctoral research positions in economics, finance and "
        "public policy outside the United States.</description>",
        "<language>en</language>",
        f"<lastBuildDate>{now}</lastBuildDate>",
    ]
    if site_url:
        parts.append(
            f'<atom:link href="{_xml_escape(site_url.rstrip("/"))}/feed.xml" '
            'rel="self" type="application/rss+xml" />'
        )

    for row in rows:
        record = _public_record(row)
        deadline = record["deadline"] or "rolling"
        description = (
            f"{record['institution']} \u2014 "
            f"{record['city'] or ''} {record['country']}".strip()
            + f". Deadline: {deadline}. "
            + record["summary"]
        )
        published = parse_datetime(record["first_seen_at"])
        pub_date = (
            published.strftime("%a, %d %b %Y %H:%M:%S +0000") if published else now
        )
        parts += [
            "<item>",
            f"<title>{_xml_escape(record['title'])} \u2014 "
            f"{_xml_escape(record['institution'])}</title>",
            f"<link>{_xml_escape(record['apply_url'])}</link>",
            f"<guid isPermaLink=\"false\">{_xml_escape(record['source_url'])}</guid>",
            f"<pubDate>{pub_date}</pubDate>",
            f"<description>{_xml_escape(description)}</description>",
        ]
        for discipline in record["disciplines"]:
            parts.append(f"<category>{_xml_escape(discipline)}</category>")
        parts.append("</item>")

    parts += ["</channel>", "</rss>"]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(parts), encoding="utf-8")
    return len(rows)
