"""Persistent, query-level, bounded LinkedIn discovery scheduling.

Each source owns one ledger, committed with the same pipeline checkpoint as
listings/career journals. An interrupted process before that git commit replays
the old ledger and discoveries rather than silently skipping fetched pages.

This module does not perform network I/O. It cannot certify provider index
completeness, employer eligibility or a vacancy's application status.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

VERSION = 1
DAY = 86400
WINDOWS = (DAY, 7 * DAY, 30 * DAY)
MAX_FILE_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_ITEMS = 3000
MAX_PAGE_ITEMS = 100
PAGE_FULL_AT = 10
PENDING_STALE_HOURS = 24
MAX_SPOOL_AGE_DAYS = 45


def _utc(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("LinkedIn query timestamps must be timezone-aware")
    return now.astimezone(UTC)


def _stamp(now: datetime) -> str:
    return _utc(now).isoformat()


def _read_time(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or len(raw) > 50:
        raise ValueError("Invalid LinkedIn query checkpoint timestamp")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return _utc(parsed)
    except ValueError as exc:
        raise ValueError("Invalid LinkedIn query checkpoint timestamp") from exc


def query_key(source: str, keyword: str, location: str) -> str:
    """Stable identity unaffected by harmless case/whitespace differences."""
    # Canonicalize the token sequences, not provider request strings.
    canonical = json.dumps([
        " ".join(str(x).casefold().split())
        for x in (source, keyword, location)
    ], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def lookback_window(
    previous: datetime | None, now: datetime,
) -> tuple[int, bool]:
    """Pick a supported window >= elapsed time + one overlap day.

    The public Jobs provider only documents coarse time filters; do not
    fabricate arbitrary day-resolution filters that may be ignored.
    An older gap than 30 days is recorded explicitly, never claimed covered.
    """
    now = _utc(now)
    if previous is None:
        return WINDOWS[-1], False
    elapsed = (now - _utc(previous)).total_seconds()
    if elapsed < 0:
        # Unexpected wall-clock rewind: prefer a broad search, but retain
        # the future timestamp in the ledger so scheduling can detect it.
        return WINDOWS[-1], True
    required = max(DAY, math.ceil(elapsed / DAY) * DAY + DAY)
    for window in WINDOWS:
        if window >= required:
            return window, False
    return WINDOWS[-1], True


@dataclass(frozen=True)
class SearchCursor:
    offset: int
    window_seconds: int
    gap: bool


class QueryLedger:
    """Single-writer per-source state with replay and fair due selection."""

    def __init__(
        self, source: str, *, max_items: int = DEFAULT_MAX_ITEMS,
        state: dict[str, Any] | None = None,
    ) -> None:
        if not source or len(source) > 120:
            raise ValueError("Invalid LinkedIn ledger source")
        if not 1 <= max_items <= 20000:
            raise ValueError("Invalid LinkedIn candidate buffer limit")
        self.source = source
        self.max_items = max_items
        self.state: dict[str, Any] = state if state is not None else {
            "version": VERSION, "source": source, "queries": {},
            "spool": {}, "dropped_age": 0,
        }
        self._validate()

    def _validate(self) -> None:
        s = self.state
        if (
            not isinstance(s, dict) or s.get("version") != VERSION
            or s.get("source") != self.source
        ):
            raise ValueError("Invalid LinkedIn ledger version or source")
        if not isinstance(s.get("queries"), dict) or not isinstance(s.get("spool"), dict):
            raise ValueError("Invalid LinkedIn ledger query or buffer structure")
        if len(s["queries"]) > 5000 or len(s["spool"]) > self.max_items:
            raise ValueError("LinkedIn ledger exceeds bounded capacity")
        for key, row in s["queries"].items():
            if not isinstance(key, str) or not isinstance(row, dict):
                raise ValueError("Invalid LinkedIn query checkpoint")
            if not isinstance(row.get("keyword"), str) or not isinstance(row.get("location"), str):
                raise ValueError("Invalid LinkedIn query identity")
            for field in ("last_complete_at", "last_attempt_at", "retry_after"):
                _read_time(row.get(field))
            pending = row.get("pending")
            if pending is not None:
                if (
                    not isinstance(pending, dict)
                    or type(pending.get("offset")) is not int
                    or not 0 <= pending["offset"] <= 10000
                    or type(pending.get("pages")) is not int
                    or not 0 <= pending["pages"] <= 50
                    or type(pending.get("window_seconds")) is not int
                    or pending["window_seconds"] not in WINDOWS
                ):
                    raise ValueError("Invalid LinkedIn pagination checkpoint")
                _read_time(pending.get("started_at"))
                _read_time(pending.get("last_page_at"))
        for ident, row in s["spool"].items():
            if (
                not isinstance(ident, str) or not ident.isascii()
                or not ident.isdecimal() or len(ident) < 6
                or not isinstance(row, dict) or not isinstance(row.get("card"), dict)
                or not isinstance(row.get("queries"), list)
            ):
                raise ValueError("Invalid LinkedIn buffered candidate")
            _read_time(row.get("observed_at"))

    @classmethod
    def load(
        cls, path: str | Path, source: str, *,
        max_items: int = DEFAULT_MAX_ITEMS,
    ) -> QueryLedger:
        dest = Path(path)
        if not dest.exists():
            return cls(source, max_items=max_items)
        try:
            if dest.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("LinkedIn ledger exceeds file size limit")
            content = json.loads(dest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError("Invalid persisted LinkedIn checkpoint; refusing overwrite") from exc
        return cls(source, max_items=max_items, state=content)

    def save(self, path: str | Path) -> None:
        """Atomic local write. Workflow commits this WITH source journals."""
        self._validate()
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            self.state, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ) + "\n"
        if len(payload.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("LinkedIn ledger exceeds maximum serialized size")
        name = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", prefix=dest.name + ".",
                suffix=".tmp", dir=dest.parent, delete=False,
            ) as handle:
                name = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, dest)
        finally:
            if name:
                Path(name).unlink(missing_ok=True)

    def _row(self, pair: tuple[str, str]) -> dict[str, Any]:
        keyword, location = pair
        key = query_key(self.source, keyword, location)
        return cast(dict[str, Any], self.state["queries"].setdefault(key, {
            "keyword": keyword, "location": location,
            "last_complete_at": None, "last_attempt_at": None,
            "retry_after": None, "pending": None, "status": "new",
            "coverage_gap": False,
        }))

    def plan(
        self, pairs: list[tuple[str, str]], *, now: datetime, limit: int,
        cooldown_hours: int = 48,
    ) -> list[tuple[str, str]]:
        """Prefer never-searched and overdue work, reserve pending-page share."""
        now = _utc(now)
        if not 1 <= limit <= 120 or not 2 <= cooldown_hours <= 720:
            raise ValueError("Invalid LinkedIn query scheduling policy")
        seen: set[str] = set()
        fresh: list[tuple[datetime, str, tuple[str, str]]] = []
        pending: list[tuple[datetime, str, tuple[str, str]]] = []
        for pair in pairs:
            if (
                len(pair) != 2 or not all(isinstance(x, str) and x.strip() for x in pair)
            ):
                raise ValueError("Invalid LinkedIn query pair")
            key = query_key(self.source, *pair)
            if key in seen:
                continue
            seen.add(key)
            row = self.state["queries"].get(key)
            if row is None:
                fresh.append((datetime.min.replace(tzinfo=UTC), key, pair))
                continue
            retry = _read_time(row.get("retry_after"))
            if retry is not None and now < retry:
                continue
            attempt = _read_time(row.get("last_attempt_at"))
            if row.get("pending") is not None:
                pending.append((attempt or datetime.min.replace(tzinfo=UTC), key, pair))
                continue
            completed = _read_time(row.get("last_complete_at"))
            if completed is None or now - completed >= timedelta(hours=cooldown_hours):
                fresh.append((completed or datetime.min.replace(tzinfo=UTC), key, pair))
        fresh.sort()
        pending.sort()
        # A large pagination backlog cannot starve never-tried searches.
        reserved = max(1, limit // 4) if pending else 0
        chosen = pending[:reserved]
        chosen.extend(fresh[:limit - len(chosen)])
        if len(chosen) < limit:
            chosen.extend(pending[reserved:reserved + limit - len(chosen)])
        return [pair for _, _, pair in chosen]

    def request(self, pair: tuple[str, str], *, now: datetime) -> SearchCursor:
        now = _utc(now)
        row = self._row(pair)
        pending = row.get("pending")
        if pending is not None:
            last_page = _read_time(pending.get("last_page_at"))
            started = _read_time(pending.get("started_at"))
            recent = last_page or started
            if recent is None or now - recent >= timedelta(hours=PENDING_STALE_HOURS):
                pending = None  # pagination can drift; restart at page 0
        if pending is None:
            lookback, gap = lookback_window(
                _read_time(row.get("last_complete_at")), now,
            )
            pending = {
                "started_at": _stamp(now), "last_page_at": None,
                "offset": 0, "pages": 0, "window_seconds": lookback,
                "coverage_gap": gap,
            }
            row["pending"] = pending
        row["last_attempt_at"] = _stamp(now)
        return SearchCursor(
            offset=pending["offset"],
            window_seconds=pending["window_seconds"],
            gap=bool(pending["coverage_gap"]),
        )

    def _prune(self, now: datetime) -> None:
        cutoff = _utc(now) - timedelta(days=MAX_SPOOL_AGE_DAYS)
        spool = self.state["spool"]
        expired = [
            ident for ident, item in spool.items()
            if (_read_time(item.get("observed_at")) or datetime.min.replace(tzinfo=UTC))
            < cutoff
        ]
        for ident in expired:
            del spool[ident]
        self.state["dropped_age"] = self.state.get("dropped_age", 0) + len(expired)

    def accept_page(
        self, pair: tuple[str, str], cards: list[dict[str, Any]], *,
        now: datetime, max_pages: int = 12,
    ) -> str:
        """Advance cursor only after storing all cards in the same ledger."""
        now = _utc(now)
        if not 1 <= max_pages <= 50 or len(cards) > MAX_PAGE_ITEMS:
            raise ValueError("LinkedIn response exceeds bounded page policy")
        key = query_key(self.source, *pair)
        row = self.state["queries"].get(key)
        if row is None or not isinstance(row.get("pending"), dict):
            raise ValueError("No active LinkedIn query to checkpoint")
        sanitized: dict[str, dict[str, Any]] = {}
        for card in cards:
            if not isinstance(card, dict):
                raise ValueError("Malformed LinkedIn card")
            ident = card.get("id")
            if (
                not isinstance(ident, str) or not ident.isascii()
                or not ident.isdecimal() or len(ident) < 6
                or not isinstance(card.get("title"), str) or not card["title"].strip()
            ):
                raise ValueError("Invalid LinkedIn card identity")
            sanitized[ident] = {
                k: str(card[k])[:4000 if k == "description" else 500]
                for k in (
                    "id", "title", "company", "location", "datetime",
                    "posted_text", "description",
                ) if card.get(k) is not None
            }
        self._prune(now)
        spool = self.state["spool"]
        if len(set(sanitized) - set(spool)) + len(spool) > self.max_items:
            row["status"] = "backpressure"
            return "backpressure"
        label = f"{pair[0]} @ {pair[1]}"
        for ident, card in sanitized.items():
            previous = spool.get(ident, {})
            queries = previous.get("queries", [])
            if label not in queries:
                queries.append(label)
            spool[ident] = {
                "card": card, "observed_at": _stamp(now),
                "queries": queries[:100],
            }
        progress = row["pending"]
        progress["last_page_at"] = _stamp(now)
        progress["pages"] += 1
        progress["offset"] += len(cards)
        row["retry_after"] = None
        if len(cards) < PAGE_FULL_AT:
            row["last_complete_at"] = progress["started_at"]
            row["coverage_gap"] = bool(progress.get("coverage_gap"))
            row["pending"] = None
            row["status"] = "complete_with_gap" if row["coverage_gap"] else "complete"
            return row["status"] if row["coverage_gap"] else "complete"
        if progress["pages"] >= max_pages:
            row["status"] = "truncated"
            row["coverage_gap"] = True
            row["pending"] = None
            row["retry_after"] = _stamp(now + timedelta(hours=48))
            return "truncated"
        row["status"] = "pending"
        return "pending"

    def fail(
        self, pair: tuple[str, str], *, now: datetime, status: int | None = None,
    ) -> None:
        """Retain last complete timestamp and cursor; defer transient errors."""
        now = _utc(now)
        row = self._row(pair)
        row["status"] = "access_limited" if status in (403, 429) else "failed"
        row["last_attempt_at"] = _stamp(now)
        row["retry_after"] = _stamp(
            now + timedelta(hours=48 if status in (403, 429) else 4),
        )

    def note_detail(self, ident: str, *, now: datetime) -> None:
        """Remember an enrichment attempt so other candidates are not starved."""
        entry = self.state["spool"].get(ident)
        if entry is not None:
            entry["detail_last_attempt_at"] = _stamp(now)

    def items(
        self, *, now: datetime, limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fairly replay candidate cards; never starve deferred enrichment.

        A bounded replay marks returned cards only as *attempted for
        downstream processing*, not published or delivered. Stable listing
        identities are still owned by the career/publication journals.
        """
        self._prune(now)
        rows = list(self.state["spool"].values())
        if limit is not None:
            if not 1 <= limit <= self.max_items:
                raise ValueError("Invalid LinkedIn replay batch size")
            untouched = [row for row in rows if not row.get("last_replayed_at")]
            if untouched:
                rows = untouched
            rows.sort(key=lambda x: (
                x.get("last_replayed_at") or "",
                -(_read_time(x["observed_at"]) or _utc(now)).timestamp(),
                x["card"].get("id", ""),
            ))
            rows = rows[:limit]
            for entry in rows:
                entry["last_replayed_at"] = _stamp(now)
        else:
            rows.sort(
                key=lambda x: x["observed_at"], reverse=True,
            )
        return [
            {
                **entry["card"],
                "_query": entry["queries"][0] if entry["queries"] else "",
                "_queries": entry["queries"][:],
                "_detail_last_attempt_at": entry.get("detail_last_attempt_at"),
            }
            for entry in rows
        ]

    def counts(self) -> dict[str, int]:
        rows = list(self.state["queries"].values())
        return {
            "checkpointed_queries": len(rows),
            "incomplete_queries": sum(r.get("pending") is not None for r in rows),
            "truncated_queries": sum(r.get("status") == "truncated" for r in rows),
            "coverage_gaps": sum(bool(r.get("coverage_gap")) for r in rows),
            "replay_candidates": len(self.state["spool"]),
            "expired_replay_candidates": int(self.state.get("dropped_age", 0)),
        }
