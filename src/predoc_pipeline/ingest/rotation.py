"""Stable, persisted source cohorts that recover missed GitHub cron runs."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEDULE_INTERVAL_HOURS = 4
MAX_HISTORY = 500


def _slot(now: datetime) -> int:
    return int(now.timestamp()) // (SCHEDULE_INTERVAL_HOURS * 3600)


def load_rotation(path: str | Path) -> dict[str, Any]:
    """Read the public source-attempt journal; malformed files are nonfatal."""
    source = Path(path)
    try:
        if not source.exists() or source.stat().st_size > 128_000:
            return {"attempts": {}, "last_slot": None}
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("attempts"), dict):
            return {"attempts": {}, "last_slot": None}
        attempts = {}
        for name, value in list(data["attempts"].items())[:MAX_HISTORY]:
            if not isinstance(name, str) or not isinstance(value, str) or len(name) > 120:
                continue
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is not None:
                attempts[name] = parsed.astimezone(UTC).isoformat()
        last_slot = data.get("last_slot")
        return {
            "attempts": attempts,
            "last_slot": last_slot if type(last_slot) is int and last_slot >= 0 else None,
        }
    except (OSError, ValueError, UnicodeError):
        return {"attempts": {}, "last_slot": None}


def scheduled_sources(
    sources: list[Any], *, timestamp: datetime | None = None,
    history: dict[str, Any] | None = None,
) -> set[str]:
    """Choose stable cohorts and catch up sources starved by missed cron slots."""
    now = (timestamp or datetime.now(UTC)).astimezone(UTC)
    slot = _slot(now)
    enabled = {s.name for s in sources if s.enabled}
    if len(enabled) < 2:
        return enabled
    data = history or {}
    attempts = data.get("attempts", {})
    if not isinstance(attempts, dict):
        attempts = {}
    last_slot = data.get("last_slot")
    missed = type(last_slot) is int and slot - last_slot >= 2
    selected = set()
    for name in enabled:
        stamp = attempts.get(name)
        if isinstance(stamp, str):
            try:
                previous = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if previous.tzinfo is not None:
                    # Compare slots: a slow/late collection must not
                    # postpone the same cohort's next 8-hour eligibility.
                    elapsed_slots = slot - _slot(previous.astimezone(UTC))
                    if 0 <= elapsed_slots < 2:
                        continue
                    selected.add(name)
                    continue
            except ValueError:
                pass
        cohort = hashlib.sha256(name.encode("utf-8")).digest()[0] % 2
        if missed or cohort == slot % 2:
            selected.add(name)
    return selected


def save_rotation(
    path: str | Path, selected: set[str], *,
    timestamp: datetime | None = None,
) -> None:
    """Commit attempts only after source collection; never commit subscriber data."""
    now = (timestamp or datetime.now(UTC)).astimezone(UTC)
    data = load_rotation(path)
    attempts = data["attempts"]
    for name in selected:
        attempts[name] = now.isoformat()
    data["attempts"] = dict(sorted(
        attempts.items(), key=lambda entry: entry[1], reverse=True,
    )[:MAX_HISTORY])
    data["last_slot"] = _slot(now)
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(dest.name + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        temp.replace(dest)
    finally:
        temp.unlink(missing_ok=True)
