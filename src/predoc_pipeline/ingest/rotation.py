"""Deterministic alternating source cohorts for a four-hour schedule."""

from __future__ import annotations

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
    return {name for index, name in enumerate(enabled) if index % 2 == slot % 2}
