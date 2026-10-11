"""Audit historical Collegeum journals and quarantine invalid public output links.

This is intentionally offline. Repair cannot prove a vacancy has closed:
non-actionable application links are excluded from public exports without
changing vacancy lifecycle, job identity, or Telegram publication receipts.
No live requests or Telegram sends are made. Run against a trusted checkout.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from predoc_pipeline.core.output_quality import (
    application_url_issue,
    authentication_page_text,
)

JOURNAL = Path("data/listings.ndjson")
DASHBOARD = Path("docs/data/listings.json")
FEED = Path("docs/feed.xml")
HEALTH = Path("docs/data/health.json")
TARGETS = (JOURNAL, DASHBOARD, FEED, HEALTH)
ITEM = re.compile(r"<item>[\s\S]*?</item>")
ITEM_LINK = re.compile(r"<link>([\s\S]*?)</link>")


def _read_journal(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"Journal line {index} is not an object")
        records.append(row)
    return records


def record_issue(record: dict[str, Any]) -> str | None:
    """Return a narrow, reproducible defect, not an inferred vacancy closure."""
    issue = application_url_issue(record.get("apply_url"))
    if issue:
        return issue
    if authentication_page_text(record.get("summary")):
        return "authentication-page-content"
    return None


def inspect(root: Path) -> dict[str, Any]:
    """Audit journal/snapshot membership and XML; never edit the input."""
    records = _read_journal(root / JOURNAL)
    published = json.loads((root / DASHBOARD).read_text(encoding="utf-8"))
    health = json.loads((root / HEALTH).read_text(encoding="utf-8"))
    xml = (root / FEED).read_text(encoding="utf-8")
    ET.fromstring(xml)
    if not isinstance(published, dict) or not isinstance(published.get("listings"), list):
        raise ValueError("Invalid dashboard listing payload")
    if not isinstance(health, dict):
        raise ValueError("Invalid health payload")
    public = published["listings"]
    seen: set[int] = set()
    hashes: set[str] = set()
    for row in records:
        identifier = row.get("id")
        identity = row.get("url_hash")
        if type(identifier) is not int or identifier in seen:
            raise ValueError("Missing or duplicate journal listing ID")
        if not isinstance(identity, str) or identity in hashes:
            raise ValueError("Missing or duplicate durable listing hash")
        seen.add(identifier)
        hashes.add(identity)
    visible_ids = [row.get("id") for row in public]
    if len(visible_ids) != len(set(visible_ids)):
        raise ValueError("Duplicate IDs in public snapshot")
    if published.get("count") != len(public):
        raise ValueError("Public snapshot count does not match the payload")
    if any(identifier not in seen for identifier in visible_ids):
        raise ValueError("Public snapshot contains listing absent from journal")

    offending = [
        {"id": row["id"], "reason": record_issue(row)}
        for row in records
        if row.get("status") == "published"
        and not row.get("closed_at")
        and not row.get("expired_at")
        and record_issue(row)
    ]
    invalid_visible = [
        row["id"] for row in public if record_issue(row)
        or (row.get("id") in {item["id"] for item in offending})
    ]
    invalid_feed = []
    for match in ITEM.finditer(xml):
        link = ITEM_LINK.search(match.group())
        if link:
            reason = application_url_issue(html.unescape(link.group(1)))
            if reason:
                # Never place URLs (which can contain access tokens) in CI logs.
                invalid_feed.append(reason)
    return {
        "journal_rows": len(records),
        "public_rows": len(public),
        "rss_items": len(ITEM.findall(xml)),
        "journal_quarantine_candidates": offending,
        "invalid_public_ids": invalid_visible,
        "invalid_rss_links": invalid_feed,
        "pipeline_outcome": (health.get("last_run") or {}).get("outcome"),
        "source_failures": (health.get("source_summary") or {}).get("failed"),
        "last_pipeline_run": (health.get("last_run") or {}).get("run_id"),
    }


def _stage(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + ".tmp")
    try:
        with staging.open("w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)


def repair(root: Path, *, when: datetime | None = None) -> dict[str, Any]:
    """Quarantine only proved non-actionable links; preserve all prior receipts.

    Originals are copied before the first write. Repairs are explicit and
    idempotent. Git history still retains previous public versions.
    """
    original = inspect(root)
    fixed_at = (when or datetime.now(UTC)).astimezone(UTC).isoformat()
    records = _read_journal(root / JOURNAL)
    dashboard = json.loads((root / DASHBOARD).read_text(encoding="utf-8"))
    health = json.loads((root / HEALTH).read_text(encoding="utf-8"))
    rss = (root / FEED).read_text(encoding="utf-8")
    # A broken application URL does NOT prove that the vacancy closed.
    # Remove it from actionable public outputs while retaining the exact
    # durable journal, delivery receipts, and source facts for remediation.
    quarantined = sorted(set(original["invalid_public_ids"]))
    excluded = set(quarantined)
    # Include any previously quarantined/invalid output references even when
    # the journal already carried a closure marker from an earlier audit.
    clean = [
        row for row in dashboard["listings"]
        if row["id"] not in excluded and not record_issue(row)
        and not next(
            (entry.get("closed_at") or entry.get("expired_at")
             for entry in records if entry["id"] == row["id"]),
            None,
        )
    ]
    dashboard["listings"] = clean
    dashboard["count"] = len(clean)

    def retain_item(match: re.Match[str]) -> str:
        found = ITEM_LINK.search(match.group())
        if not found:
            return match.group()
        return "" if application_url_issue(
            html.unescape(found.group(1))
        ) else match.group()

    rss = ITEM.sub(retain_item, rss)
    if quarantined or original["invalid_rss_links"]:
        dashboard["output_audited_at"] = fixed_at
        # Do not modify closed/expired inventory counts: a bad link is
        # a publication-quality problem, not an observed vacancy closure.
        health["output_audit"] = {
            "reviewed_at": fixed_at,
            "quarantined_ids": sorted(quarantined),
            "reason": "suppressed invalid application links; vacancy status unchanged",
            "historical_run": original["last_pipeline_run"],
        }

        backup = root / "build" / f"output-audit-backup-{fixed_at.replace(':', '-')}"
        backup.mkdir(parents=True, exist_ok=False)
        for relative in TARGETS:
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / relative, saved)
        _stage(root / DASHBOARD, json.dumps(dashboard, ensure_ascii=False, indent=1) + "\n")
        _stage(root / FEED, rss)
        _stage(root / HEALTH, json.dumps(health, ensure_ascii=False, indent=1) + "\n")
    updated = inspect(root)
    if updated["invalid_public_ids"] or updated["invalid_rss_links"]:
        raise RuntimeError("Output repair left unresolved non-actionable records")
    return {"before": original, "after": updated, "quarantined_ids": sorted(quarantined)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = repair(args.root) if args.repair else inspect(args.root)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    if not args.repair and any((
        result["invalid_public_ids"],
        result["invalid_rss_links"],
    )):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
