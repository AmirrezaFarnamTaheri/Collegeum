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
    """Read a complete journal; malformed records must not become partial recovery."""
    file = Path(path)
    if not file.exists():
        return []
    out: list[dict[str, Any]] = []
    for number, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"invalid journal {file} at line {number}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"journal {file} line {number} must be an object")
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
    """Reconcile the derived database with complete committed journals.

    This is what makes the derived-cache model safe: a fresh clone, a cleared
    runner, or a corrupted file all recover by replaying the journal.
    """
    restored = 0
    with db.transaction():
        seen = read_journal(seen_path) if seen_path else []
        records = read_journal(path)
        if records:
            restored = db.import_rows(records)
        if seen:
            db.import_seen(seen)
    return restored


def restore_runs(db: Any, health_path: str | Path) -> int:
    """Rebuild the run log from docs/data/health.json when the database is fresh."""
    file = Path(health_path)
    if not file.exists():
        return 0
    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"invalid health state in {file}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"health state must be an object: {file}")
    usage = payload.get("llm_usage", [])
    if not isinstance(usage, list):
        raise ValueError(f"quota usage must be a list: {file}")
    history = payload.get("runs", [])
    if not isinstance(history, list) or any(not isinstance(run, dict) for run in history):
        raise ValueError(f"run history must be a list of objects: {file}")
    runs = [run for run in history if run.get("finished_at")]
    with db.transaction():
        db.import_llm_usage(usage)
        if db.counts()["runs"] > 1:  # the current run is already in there
            return 0
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
    days_left = (parsed.date() - utcnow().date()).days if parsed else None

    tools_req: list[str] = []
    try:
        tools_req = json.loads(_row_value(row, "tools_required") or "[]")
    except (ValueError, TypeError):
        pass

    tools_pref: list[str] = []
    try:
        tools_pref = json.loads(_row_value(row, "tools_preferred") or "[]")
    except (ValueError, TypeError):
        pass

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
        "salary_min": _row_value(row, "salary_min"),
        "salary_max": _row_value(row, "salary_max"),
        "salary_currency": _row_value(row, "salary_currency"),
        "salary_period": _row_value(row, "salary_period"),
        "salary_raw": _row_value(row, "salary_raw"),
        "tools_required": tools_req,
        "tools_preferred": tools_pref,
        "min_degree": _row_value(row, "min_degree"),
        "degree_note": _row_value(row, "degree_note"),
        "start_term": _row_value(row, "start_term"),
        "start_date": _row_value(row, "start_date"),
    }


def _web_rows(db: Any, hidden: set[str], router: Any | None) -> list[Any]:
    """Active listings for the website: hidden ones out, Telegram-only ones out."""
    return [
        row
        for row in db.active_listings()
        if row["url_hash"] not in hidden
        and (router is None or router.channel_for_row(row) == "web")
    ]


def export_dashboard(
    db: Any, path: str | Path, *, hidden: set[str] | None = None, router: Any | None = None
) -> int:
    """Write the JSON snapshot the static dashboard fetches.

    ``hidden`` holds the url_hash of positions marked ❌ in Telegram. With a
    ``router``, only listings routed to the website are included.
    """
    records = []
    for row in _web_rows(db, hidden or set(), router):
        record = _public_record(row)
        if router is not None:
            record["kind"] = router.position_kind(row["title"], row["summary"] or "")
            record["sector"] = router.sector(row["institution"] or "")
        records.append(record)
    payload = {
        "generated_at": format_ts(),
        "count": len(records),
        "listings": records,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(records)


def export_health(
    db: Any, path: str | Path, *, stats: dict[str, Any], preserve_existing: bool = False
) -> None:
    """Write run history and per-source yield, so failures are visible.

    A dashboard that only shows listings cannot distinguish "a quiet week" from
    "every scraper has been broken since the portal redesign". This file is
    what makes that difference legible without reading workflow logs.
    """
    from .core.health import public_source_stats, source_status, source_summary

    target = Path(path)
    previous = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    if not isinstance(previous, dict):
        raise ValueError(f"health state must be an object: {target}")

    runs = []
    sources: dict[str, Any] = {}
    for row in db.recent_runs(limit=30):
        try:
            source_stats = json.loads(row["source_stats"] or "{}")
        except ValueError:
            source_stats = {}
        public_stats = public_source_stats(source_stats)
        for name, data in public_stats.items():
            if name.startswith("_") or not row["finished_at"]:
                continue
            status = source_status(data)
            entry = sources.setdefault(name, {
                "status": status, "last_attempt_at": row["finished_at"],
                "last_successful_at": None, "messages": data["messages"],
            })
            if entry["last_successful_at"] is None and status in {"successful", "empty"} and (
                data.get("fetched") or data.get("unchanged") or data.get("ok") is True
            ):
                entry["last_successful_at"] = row["finished_at"]
        runs.append(
            {
                "source_stats": public_stats,
                "source_summary": source_summary(source_stats),
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
    latest = runs[0] if runs else {}
    summary = latest.get("source_summary") or source_summary({})
    outcome = stats.get("outcome") or latest.get("outcome") or "unknown"
    status = "degraded" if outcome == "partial" or (
        outcome == "ok" and (summary["failed"] or stats.get("errors"))
    ) else outcome
    # Retain known successful times after they age out of the 30-run history.
    # Validate the timestamp before carrying it forward from the prior export.
    def previous_success(value: Any) -> str | None:
        moment = parse_datetime(value) if isinstance(value, str) else None
        return value if moment is not None and moment <= utcnow() else None

    previous_sources = previous.get("sources") or {}
    if isinstance(previous_sources, dict):
        for name, entry in sources.items():
            old = previous_sources.get(name)
            if entry["last_successful_at"] is None and isinstance(old, dict):
                entry["last_successful_at"] = previous_success(old.get("last_successful_at"))
    last_success = next((run["finished_at"] for run in runs if run["outcome"] == "ok"
                         and not run["source_summary"]["failed"]), None)
    payload = {
        "generated_at": format_ts(),
        "counts": db.counts(),
        "last_run": stats,
        "runs": runs,
        "status": status,
        "source_summary": summary,
        "sources": sources,
        "llm_usage": db.export_llm_usage(),
        "last_successful_run_at": last_success or previous_success(
            previous.get("last_successful_run_at")
        ),
    }
    if preserve_existing:
        # Restoration failed before this DB became authoritative. Report the
        # failed run without replacing durable quota usage or prior inventory.
        # A malformed existing JSON file raises above and stays untouched.
        payload = {
            **previous,
            "generated_at": format_ts(), "status": stats.get("outcome", "fatal"),
            "last_run": stats, "source_summary": summary,
            "runs": (runs + (previous.get("runs") or []))[:30],
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(target)


# --------------------------------------------------------------------------
# Public RSS
# --------------------------------------------------------------------------

_RSS_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}


def _xml_escape(value: str) -> str:
    return "".join(_RSS_ESCAPES.get(c, c) for c in str(value or "") if (
        c in "\t\n\r" or 0x20 <= ord(c) <= 0xD7FF
        or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF
    ))


def export_feed(
    db: Any,
    path: str | Path,
    *,
    site_url: str = "",
    limit: int = 100,
    hidden: set[str] | None = None,
    router: Any | None = None,
    title: str = "Collegeum — Research Positions",
) -> int:
    """Publish the website's listings as RSS as well.

    Removes any single channel as the only way in: anyone can subscribe in a
    reader, and the data stays usable if a bot token is ever revoked.
    """
    rows = _web_rows(db, hidden or set(), router)[:limit]
    now = utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<?xml-stylesheet type="text/xsl" href="rss.xsl"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        f"<title>{_xml_escape(title)}</title>",
        f"<link>{_xml_escape(site_url or 'https://example.invalid')}</link>",
        "<description>US research positions, PhD and postdoc posts, and openings at "
        "central banks, international organizations and firms.</description>",
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
            f"{record['institution']} \u2014 {record['city'] or ''} {record['country']}".strip()
            + f". Deadline: {deadline}. "
            + record["summary"]
        )
        published = parse_datetime(record["first_seen_at"])
        pub_date = published.strftime("%a, %d %b %Y %H:%M:%S +0000") if published else now
        parts += [
            "<item>",
            f"<title>{_xml_escape(record['title'])} \u2014 "
            f"{_xml_escape(record['institution'])}</title>",
            f"<link>{_xml_escape(record['apply_url'])}</link>",
            f'<guid isPermaLink="false">{_xml_escape(record["source_url"])}</guid>',
            f"<pubDate>{pub_date}</pubDate>",
            f"<description>{_xml_escape(description)}</description>",
        ]
        for discipline in record["disciplines"]:
            parts.append(f"<category>{_xml_escape(discipline)}</category>")
        parts.append("</item>")

    parts += ["</channel>", "</rss>"]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text("\n".join(parts), encoding="utf-8")
    tmp.replace(target)
    return len(rows)
