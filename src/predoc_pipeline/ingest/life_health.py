"""Public, source-scoped diagnostics for opt-in Life Sciences PhD discovery.

This file intentionally contains no subscriber, Telegram, journal, or
credential data. A source with 0 recognized links is NOT healthy merely
because its landing page returned HTTP 200.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def read_life_health(path: str | Path) -> dict[str, Any]:
    """Read a small historical public health file; corruption never blocks jobs."""
    source = Path(path)
    try:
        if not source.exists() or source.stat().st_size > 256_000:
            return {}
        result = json.loads(source.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, UnicodeError, ValueError):
        return {}


def write_life_health(
    path: str | Path, *, sources: list[Any],
    diagnostics: dict[str, dict[str, Any]], started: datetime | None = None,
) -> None:
    """Persist observations without erasing feeds not sampled this rotation.

    A per-source status is only evidence of the *index*, never proof that
    specific doctoral ads are open, eligible, or fully funded. Prior successful
    observations remain timestamped but are not projected as fresh successes.
    """
    now = (started or datetime.now(UTC)).astimezone(UTC).isoformat()
    previous = read_life_health(path).get("sources")
    history = previous if isinstance(previous, dict) else {}
    enabled = {s.name for s in sources if s.enabled}
    records: dict[str, dict[str, Any]] = {}
    for name in sorted(enabled):
        old = history.get(name)
        entry = dict(old) if isinstance(old, dict) else {
            "status": "never_checked", "vacancy_links": 0,
            "doctoral_candidates": 0, "matched_candidates": 0,
        }
        new = diagnostics.get(name)
        if new is not None:
            entry.update({
                "status": str(new.get("status", "unknown")),
                "vacancy_links": int(new.get("vacancy_links", 0)),
                "doctoral_candidates": int(new.get("doctoral_candidates", 0)),
                "matched_candidates": int(new.get("matched_candidates", 0)),
                "discovery_issues": int(new.get("discovery_issues", 0)),
                "detail_failures": int(new.get("detail_failures", 0)),
                "last_checked_at": now,
            })
            if entry["status"] in ("discovered", "verified_empty"):
                entry["last_success_at"] = now
        records[name] = entry

    updated = {k: records[k] for k in diagnostics if k in records}
    result = {
        "checked_at": now,
        "catalogue": {
            "total": len(sources), "enabled": len(enabled),
            "disabled": len(sources) - len(enabled),
        },
        "checked_this_run": len(updated),
        "summary_this_run": {
            state: sum(v["status"] == state for v in updated.values())
            for state in (
                "discovered", "verified_empty", "unverified_empty",
                "partial", "failed", "skipped", "unsupported",
            )
        },
        "sources": records,
        "notes": (
            "Index observations, not proof of open/funded jobs. "
            "Unselected source records remain historical and timestamped."
        ),
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)
