"""Deterministic alternating source cohorts for a three-hour schedule."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def scheduled_sources(sources: list[Any], *, timestamp: datetime | None = None) -> set[str]:
    """Poll every enabled board once per six hours, in two stable cohorts."""
    now = timestamp or datetime.now(UTC)
    slot = int(now.timestamp()) // (3 * 3600)
    enabled = sorted(s.name for s in sources if s.enabled)
    if len(enabled) < 2:
        return set(enabled)
    return {name for index, name in enumerate(enabled) if index % 2 == slot % 2}
