"""Read-only, source-safe quality profile of both Collegeum position ledgers.

Run: python -m tools.audit_stored_positions
Output contains only counts and durable IDs, never signed application URLs.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    result = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    if not all(isinstance(row, dict) for row in result):
        raise ValueError(f"Expected JSON objects in {path.name}")
    return result


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _blank(value: object) -> bool:
    return value in (None, "", "unknown", "unstated", "not stated")


def _duplicate_values(rows: list[dict[str, Any]], field: str) -> list[str]:
    counts = Counter(str(row.get(field)) for row in rows)
    return sorted(value for value, count in counts.items() if count > 1)


def audit(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Keep mixed journal/career grains separate and expose actionable issues."""
    jobs = _rows(root / "data/listings.ndjson")
    career = _rows(root / "data/career_jobs.ndjson")
    at = (now or datetime.now(UTC)).astimezone(UTC)
    missing_country = [row["id"] for row in jobs if _blank(row.get("country"))]
    ambiguous_degree = [
        row["id"] for row in jobs if _blank(row.get("min_degree"))
    ]
    passed_deadlines = [
        row["id"] for row in jobs
        if (dt := _timestamp(row.get("deadline"))) and dt < at
    ]
    unmarked_expiry = [
        row["id"] for row in jobs
        if row["id"] in passed_deadlines and not row.get("expired_at")
    ]
    confirmed = [
        row["id"] for row in jobs
        if row.get("telegram_delivery_state") == "confirmed"
    ]
    legacy = [
        row["id"] for row in jobs
        if row.get("telegram_message_id") is not None
        and row.get("telegram_delivery_state") != "confirmed"
    ]
    bad_receipts = [
        row["id"] for row in jobs
        if row.get("telegram_delivery_state") == "confirmed"
        and not isinstance(row.get("telegram_message_id"), int)
    ]
    mismatches = [
        row["id"] for row in jobs
        if re.search(r"\bLocation:\s*Colombia\b", row.get("summary") or "", re.I)
        and row.get("country") != "Colombia"
    ]
    numeric_locations = [
        row["key"] for row in career if re.fullmatch(
            r"\d{1,8}", str(row.get("location") or ""),
        )
    ]
    scope_review = [
        row["key"] for row in career
        if row.get("category") == "life_sciences_phd"
        and re.search(
            r"\b(?:symbolic AI|nationalekonomi|computing science)\b",
            row.get("title") or "", re.I,
        )
    ]
    violations = []
    for field in ("id", "url_hash"):
        duplicates = _duplicate_values(jobs, field)
        if duplicates:
            violations.append(f"duplicate journal {field}: {len(duplicates)}")
    if duplicates := _duplicate_values(career, "key"):
        violations.append(f"duplicate career key: {len(duplicates)}")
    if bad_receipts:
        violations.append(f"confirmed Telegram state missing receipt: {len(bad_receipts)}")

    return {
        "as_of_utc": at.isoformat(),
        "grain": {"journal": "one accepted URL identity", "career": "one career key"},
        "journal": {
            "rows": len(jobs),
            "status_counts": dict(sorted(Counter(
                str(row.get("status")) for row in jobs
            ).items())),
            "missing_country_ids": missing_country,
            "missing_country": len(missing_country),
            "unknown_min_degree": len(ambiguous_degree),
            "missing_deadline": sum(_blank(row.get("deadline")) for row in jobs),
            "past_deadline": len(passed_deadlines),
            "past_deadline_without_expiry_marker_ids": unmarked_expiry,
            "confirmed_phd_receipts": len(confirmed),
            "legacy_predoc_message_ids": len(legacy),
            "country_disagreement_ids": mismatches,
        },
        "career": {
            "rows": len(career),
            "categories": dict(sorted(Counter(
                str(row.get("category")) for row in career
            ).items())),
            "missing_country": sum(_blank(row.get("country")) for row in career),
            "missing_deadline": sum(_blank(row.get("deadline")) for row in career),
            "numeric_location_keys": numeric_locations,
            "off_topic_life_sciences_review_keys": scope_review,
        },
        "critical_invariants": violations,
        "notes": (
            "Legacy Predoc messages are not failed PhD delivery states. "
            "Past journal deadlines are historical, not evidence of a new failure. "
            "Career entries have a different grain and may mirror journal vacancies."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.root)
    serialized = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    if result["critical_invariants"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
