"""Deterministic alternating source cohorts for a four-hour schedule."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

SCHEDULE_INTERVAL_HOURS = 4


def scheduled_sources(sources: list[Any], *, timestamp: datetime | None = None) -> set[str]:
    """Poll each enabled source once per eight hours, in two stable cohorts."""
    now = timestamp or datetime.now(UTC)
    slot = int(now.timestamp()) // (SCHEDULE_INTERVAL_HOURS * 3600)
    enabled = sorted(s.name for s in sources if s.enabled)
    if len(enabled) < 2:
        return set(enabled)
    # Stable across new, renamed or disabled unrelated sources.
    return {
        name for name in enabled
        if hashlib.sha256(name.encode("utf-8")).digest()[0] % 2 == slot % 2
    }
