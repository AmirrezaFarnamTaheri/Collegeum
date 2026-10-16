"""Reconcile historical audit-only false closures without changing delivery receipts.

Use --apply on a clean, trusted checkout during a paused pipeline. This is an
explicit one-time migration, not a scheduled job. Invalid application links
remain suppressed by the existing public-output quarantine checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AUDIT_CLOSURE_PREFIX = "output audit: non-actionable application link ("
JOURNAL = Path("data/listings.ndjson")


def _parse_records(data: bytes) -> list[dict[str, Any]]:
    seen: set[int] = set()
    records: list[dict[str, Any]] = []
    for number, line in enumerate(data.decode("utf-8").split("\n"), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        identifier = record.get("id") if isinstance(record, dict) else None
        if type(identifier) is not int or identifier <= 0 or identifier in seen:
            raise ValueError(f"invalid or duplicate journal ID on line {number}")
        seen.add(identifier)
        records.append(record)
    return records


def false_audit_closure(row: dict[str, Any]) -> bool:
    """Only the unique audit-generated marker; never infer source closure."""
    reason = row.get("closed_reason")
    return bool(
        row.get("closed_at")
        and isinstance(reason, str)
        and reason.startswith(AUDIT_CLOSURE_PREFIX)
        and reason.endswith(")")
        and row.get("status") == "published"
    )


def _atomic_replace(path: Path, data: bytes) -> None:
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def reconcile(root: Path, *, apply: bool = False) -> dict[str, Any]:
    """Preview or repair a journal, backing up exact original bytes first.

    No Telegram messages, closed-job reclassifications, or public exports are
    performed. The next explicit pipeline run regenerates its safe exports.
    """
    path = root / JOURNAL
    raw = path.read_bytes()
    records = _parse_records(raw)
    candidates = [record for record in records if false_audit_closure(record)]
    ids = sorted(record["id"] for record in candidates)
    result: dict[str, Any] = {"candidate_ids": ids, "applied": False, "backup": None}
    if not apply or not candidates:
        return result

    for record in candidates:
        record["closed_at"] = None
        record["closed_reason"] = None
    rendered = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records
    ).encode("utf-8")
    # Create an immutable, content-addressed copy before touching the journal.
    before_hash = hashlib.sha256(raw).hexdigest()
    backups = root / "build" / "false-audit-closure-backups"
    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / f"listings-{before_hash[:20]}.ndjson"
    if backup.exists():
        if backup.read_bytes() != raw:
            raise ValueError("existing repair backup content does not match journal")
    else:
        with backup.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    # Fail if another process replaced the journal during validation.
    if path.read_bytes() != raw:
        raise RuntimeError("journal changed during false-closure migration")
    _atomic_replace(path, rendered)
    result["applied"] = True
    result["backup"] = str(backup.relative_to(root))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--apply", action="store_true", help="write with an exact-byte backup")
    args = parser.parse_args()
    result = reconcile(args.root, apply=args.apply)
    result["checked_at"] = datetime.now(UTC).isoformat()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
