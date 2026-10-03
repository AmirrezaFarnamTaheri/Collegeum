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
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

__all__ = ["QuotaExceeded", "RateLimiter", "quota_day"]

# America/Los_Angeles without a tzdata dependency: PST is UTC-8, PDT UTC-7.
# Being an hour off at a DST boundary shifts the reset by an hour, which is
# harmless; being eight hours off (UTC) is not.
_PACIFIC_STANDARD_OFFSET = timedelta(hours=-8)
_PACIFIC_DAYLIGHT_OFFSET = timedelta(hours=-7)


def _pacific_offset(moment: datetime) -> timedelta:
    """Rough US DST window: second Sunday in March to first Sunday in November."""
    year = moment.year
    march = datetime(year, 3, 8, tzinfo=UTC)
    dst_start = march + timedelta(days=(6 - march.weekday()) % 7)
    november = datetime(year, 11, 1, tzinfo=UTC)
    dst_end = november + timedelta(days=(6 - november.weekday()) % 7)
    return _PACIFIC_DAYLIGHT_OFFSET if dst_start <= moment < dst_end else _PACIFIC_STANDARD_OFFSET


def quota_day(moment: datetime | None = None) -> str:
    """The provider's quota day (YYYY-MM-DD) that `moment` falls in."""
    now = moment or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return (now.astimezone(UTC) + _pacific_offset(now)).strftime("%Y-%m-%d")


class QuotaExceeded(RuntimeError):
    """Raised when the daily request budget is exhausted."""


class _DailyCounter(Protocol):
    def llm_usage(self, day: str) -> tuple[int, int]: ...
    def record_llm_call(self, day: str, *, tokens: int = 0, error: bool = False) -> int: ...


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
    _lock: Any = field(default_factory=threading.RLock)

    def __post_init__(self) -> None:
        self._allowance = float(self.requests_per_minute)
        self._last_check = time.monotonic()

    # -- daily budget -----------------------------------------------------
    @property
    def daily_budget(self) -> int:
        return max(1, int(self.requests_per_day * self.safety_margin))

    def remaining_today(self, day: str | None = None) -> int:
        key = day or quota_day()
        with self._lock:
            used = self.store.llm_usage(key)[0] if self.store else self._local_calls
            return max(0, self.daily_budget - used)

    def check_budget(self, day: str | None = None) -> None:
        if self.remaining_today(day) <= 0:
            raise QuotaExceeded(
                f"daily model request budget exhausted "
                f"({self.daily_budget} of {self.requests_per_day} planned)"
            )

    # -- per-minute pacing ------------------------------------------------
    def acquire(self, *, day: str | None = None, sleep=time.sleep) -> None:
        """Block until a request may be sent, or raise if the day is spent."""
        to_sleep = 0.0
        with self._lock:
            self.check_budget(day)
            rate = max(1, self.requests_per_minute)
            now = time.monotonic()
            self._allowance += (now - self._last_check) * (rate / 60.0)
            self._last_check = now
            if self._allowance > rate:
                self._allowance = float(rate)
            if self._allowance < 1.0:
                to_sleep = (1.0 - self._allowance) * (60.0 / rate)
                self._allowance = 0.0
            else:
                self._allowance -= 1.0
        if to_sleep > 0.0:
            sleep(to_sleep)
            with self._lock:
                self._last_check = time.monotonic()

    def record(self, *, tokens: int = 0, error: bool = False, day: str | None = None) -> None:
        key = day or quota_day()
        with self._lock:
            self._local_calls += 1
            if self.store is not None:
                self.store.record_llm_call(key, tokens=tokens, error=error)

    def penalise(self, seconds: float) -> None:
        """Apply a provider-instructed backoff to the bucket."""
        with self._lock:
            self._allowance = 0.0
            self._last_check = time.monotonic() + max(0.0, seconds)
