"""Local quota enforcement for the model provider. Stdlib only.

The provider no longer publishes a fixed free-tier table -- current docs say
limits "depend on a variety of factors" and are visible only in the console --
so hard-coding "15 RPM / 1500 RPD" as an architectural constant is unsound.
Instead the limits are configuration with conservative defaults, enforced here
before a request is made, and the provider's own 429 (with its RetryInfo
delay) remains the authority when our estimate is wrong.

Two independent constraints:

* **Requests per minute** -- a token bucket over a monotonic clock. Sleeps
  only as long as necessary, never a flat `sleep(1.2)` per call.
* **Requests per day** -- a counter persisted in SQLite, keyed by the
  provider's quota day. Quota days reset at midnight America/Los_Angeles, not
  UTC, so a UTC-keyed counter drifts by up to eight hours and lets a run blow
  through the cap while believing it has budget.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

__all__ = ["QuotaExceeded", "RateLimiter", "quota_day"]

# America/Los_Angeles without a tzdata dependency: PST is UTC-8, PDT UTC-7.
# Transition instants use UTC: 02:00 PST in March and 02:00 PDT in November.
_PACIFIC_STANDARD_OFFSET = timedelta(hours=-8)
_PACIFIC_DAYLIGHT_OFFSET = timedelta(hours=-7)


def _pacific_offset(moment: datetime) -> timedelta:
    """Current US DST rule, with the actual transition hours."""
    year = moment.year
    march = datetime(year, 3, 8, 10, tzinfo=UTC)
    dst_start = march + timedelta(days=(6 - march.weekday()) % 7)
    november = datetime(year, 11, 1, 9, tzinfo=UTC)
    dst_end = november + timedelta(days=(6 - november.weekday()) % 7)
    return _PACIFIC_DAYLIGHT_OFFSET if dst_start <= moment < dst_end else _PACIFIC_STANDARD_OFFSET


def quota_day(moment: datetime | None = None) -> str:
    """The provider's quota day (YYYY-MM-DD) that `moment` falls in."""
    now = moment or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now = now.astimezone(UTC)
    return (now + _pacific_offset(now)).strftime("%Y-%m-%d")


class QuotaExceeded(RuntimeError):
    """Raised when the daily request budget is exhausted."""


class _DailyCounter(Protocol):
    def llm_usage(self, day: str) -> tuple[int, int]: ...
    def reserve_llm_call(self, day: str, budget: int) -> bool: ...
    def record_llm_result(self, day: str, *, tokens: int = 0, error: bool = False) -> None: ...


@dataclass(slots=True)
class RateLimiter:
    """Token bucket for RPM plus a persisted daily counter for RPD."""

    requests_per_minute: int = 10
    requests_per_day: int = 200
    store: _DailyCounter | None = None
    safety_margin: float = 0.9      # never plan to use the last 10% of the day's quota
    _allowance: float = 0.0
    _last_check: float = 0.0
    _local_calls: int = 0
    _local_usage: dict[str, int] = field(default_factory=dict)
    _lock: Any = field(default_factory=threading.RLock)

    def __post_init__(self) -> None:
        if self.requests_per_minute < 1 or self.requests_per_day < 1:
            raise ValueError("model request limits must be positive")
        if not 0 < self.safety_margin <= 1:
            raise ValueError("model quota safety margin must be in (0, 1]")
        self._allowance = float(self.requests_per_minute)
        self._last_check = time.monotonic()

    # -- daily budget -----------------------------------------------------
    @property
    def daily_budget(self) -> int:
        return max(1, int(self.requests_per_day * self.safety_margin))

    def remaining_today(self, day: str | None = None) -> int:
        key = day or quota_day()
        with self._lock:
            used = self.store.llm_usage(key)[0] if self.store else self._local_usage.get(key, 0)
            return max(0, self.daily_budget - used)

    def check_budget(self, day: str | None = None) -> None:
        if self.remaining_today(day) <= 0:
            raise QuotaExceeded(
                f"daily model request budget exhausted "
                f"({self.daily_budget} of {self.requests_per_day} planned)"
            )

    # -- per-minute pacing ------------------------------------------------
    def _reserve_locked(self, key: str) -> None:
        if self.store is not None:
            reserved = self.store.reserve_llm_call(key, self.daily_budget)
        else:
            reserved = self._local_usage.get(key, 0) < self.daily_budget
            if reserved:
                self._local_usage[key] = self._local_usage.get(key, 0) + 1
        if not reserved:
            raise QuotaExceeded(
                f"daily model request budget exhausted "
                f"({self.daily_budget} of {self.requests_per_day} planned)"
            )
        self._local_calls += 1

    def acquire(
        self, *, day: str | None = None, sleep: Callable[[float], None] = time.sleep,
    ) -> str:
        """Reserve one attempt atomically, pace it, and return its quota day.

        Reservations are conservative: an interrupted waiter still consumes its
        slot. Never release one after an uncertain transport outcome.
        """
        key = day or quota_day()
        to_sleep = 0.0
        with self._lock:
            self._reserve_locked(key)
            rate = max(1, self.requests_per_minute)
            now = time.monotonic()
            penalty = max(0.0, self._last_check - now)
            refill = max(0.0, now - self._last_check) * (rate / 60.0)
            self._allowance = min(float(rate), self._allowance + refill)
            self._last_check = max(now, self._last_check)
            self._allowance -= 1.0
            if self._allowance < 0.0:
                to_sleep = -self._allowance * (60.0 / rate)
            if penalty > 0.0:
                to_sleep += penalty
        if to_sleep > 0.0:
            sleep(to_sleep)
        if day is None:
            actual_day = quota_day()
            if actual_day != key:
                # A pacing wait can cross midnight. Keep the old reservation
                # conservatively, but enforce the new day's budget before sending.
                with self._lock:
                    self._reserve_locked(actual_day)
                key = actual_day
        return key

    def record(self, *, tokens: int = 0, error: bool = False, day: str | None = None) -> None:
        """Attach an outcome to an acquired request; do not spend another slot."""
        key = day or quota_day()
        with self._lock:
            if self.store is not None:
                self.store.record_llm_result(key, tokens=tokens, error=error)

    def penalise(self, seconds: float) -> None:
        """Apply a provider-instructed backoff to the bucket."""
        with self._lock:
            self._allowance = 0.0
            self._last_check = time.monotonic() + max(0.0, seconds)
