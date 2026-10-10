"""SQLite storage. Stdlib only.

Design notes that matter operationally:

* The connection runs in real autocommit mode (`isolation_level=None`) and
  every multi-statement write goes through `transaction()`, which issues an
  explicit `BEGIN IMMEDIATE`. Python's default `isolation_level=""` starts
  transactions implicitly before DML only, which makes it genuinely hard to
  reason about what is atomic.

* Timestamps are `YYYY-MM-DDTHH:MM:SSZ`, always UTC. Comparisons against
  "N days ago" use `strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)` so the operands
  share a format. Comparing an offset-bearing ISO string against SQLite's
  `datetime('now')` (space separator, no offset) only appears to work.

* `checkpoint()` runs `PRAGMA wal_checkpoint(TRUNCATE)` before the workflow
  commits the database file. Without it the newest transactions may still live
  in `-wal`, and a job that commits only `predocs.db` silently ships a
  database missing its most recent writes.

* `seen_items` is the pre-extraction gate. A source URL we have already
  judged never reaches the model again, which is what keeps daily LLM usage
  proportional to *new* postings rather than to feed size.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, cast

from .timeparse import format_ts

_log = logging.getLogger(__name__)

__all__ = [
    "SCHEMA_VERSION",
    "connect",
    "init",
    "transaction",
    "now",
    "since",
    "Database",
]

SCHEMA_VERSION = 6

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS listings (
  id                        INTEGER PRIMARY KEY AUTOINCREMENT,
  url_hash                  TEXT    NOT NULL UNIQUE,
  apply_url                 TEXT    NOT NULL,
  source_url                TEXT    NOT NULL,
  source                    TEXT    NOT NULL DEFAULT '',
  title                     TEXT    NOT NULL,
  institution               TEXT    NOT NULL,
  principal_investigator    TEXT,
  country                   TEXT    NOT NULL DEFAULT '',
  city                      TEXT,
  is_remote                 INTEGER NOT NULL DEFAULT 0,
  duration_years            REAL,
  deadline                  TEXT,
  disciplines               TEXT    NOT NULL DEFAULT '[]',
  visa_sponsorship_status   TEXT    NOT NULL DEFAULT 'unknown',
  summary                   TEXT    NOT NULL DEFAULT '',
  language                  TEXT    NOT NULL DEFAULT 'en',
  model_confidence          REAL    NOT NULL DEFAULT 0,
  rule_score                REAL    NOT NULL DEFAULT 0,
  confidence                REAL    NOT NULL DEFAULT 0,
  signature                 BLOB,
  alternate_sources         TEXT    NOT NULL DEFAULT '[]',
  telegram_message_id       INTEGER,
  x_post_id                 TEXT,
  status                    TEXT    NOT NULL DEFAULT 'pending',
  first_seen_at             TEXT    NOT NULL,
  last_seen_at              TEXT    NOT NULL,
  published_at              TEXT,
  expired_at                TEXT,
  deadline_note             TEXT,
  visa_note                 TEXT,
  closed_reason             TEXT,
  closed_at                 TEXT,
  last_checked_at           TEXT,
  department                TEXT,
  fields                    TEXT,
  salary_min                REAL,
  salary_max                REAL,
  salary_currency           TEXT,
  salary_period             TEXT,
  salary_raw                TEXT,
  tools_required            TEXT    NOT NULL DEFAULT '[]',
  tools_preferred           TEXT    NOT NULL DEFAULT '[]',
  min_degree                TEXT,
  degree_note               TEXT,
  start_term                TEXT,
  start_date                TEXT
);
CREATE INDEX IF NOT EXISTS ix_listings_status     ON listings(status);
CREATE INDEX IF NOT EXISTS ix_listings_deadline   ON listings(deadline);
CREATE INDEX IF NOT EXISTS ix_listings_seen       ON listings(first_seen_at);
CREATE INDEX IF NOT EXISTS ix_listings_inst       ON listings(institution);
CREATE INDEX IF NOT EXISTS ix_listings_apply_url  ON listings(apply_url);
CREATE INDEX IF NOT EXISTS ix_listings_source_url ON listings(source_url);
CREATE INDEX IF NOT EXISTS ix_listings_active     ON listings(first_seen_at DESC)
  WHERE status='published' AND expired_at IS NULL AND closed_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_listings_identity   ON listings(
  LOWER(TRIM(institution)), LOWER(TRIM(title))
) WHERE status='published' AND closed_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_listings_pending    ON listings(id)
  WHERE status IN ('pending', 'unpublished') AND closed_at IS NULL AND expired_at IS NULL;

-- Every source URL we have ever formed an opinion about, and what that
-- opinion was. Consulted before any network or model spend.
CREATE TABLE IF NOT EXISTS seen_items (
  url_hash      TEXT PRIMARY KEY,
  source        TEXT NOT NULL DEFAULT '',
  decision      TEXT NOT NULL,          -- gated | rejected | duplicate | published | error
  reason        TEXT NOT NULL DEFAULT '',
  content_hash  TEXT NOT NULL DEFAULT '',
  listing_id    INTEGER,
  first_seen_at TEXT NOT NULL,
  last_seen_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_seen_decision ON seen_items(decision);

-- Conditional-GET bookkeeping so unchanged feeds cost one 304 per day.
CREATE TABLE IF NOT EXISTS http_cache (
  url_hash      TEXT PRIMARY KEY,
  url           TEXT NOT NULL,
  etag          TEXT,
  last_modified TEXT,
  body_hash     TEXT,
  fetched_at    TEXT NOT NULL,
  status        INTEGER NOT NULL DEFAULT 0
);

-- Local accounting against the model provider's daily quota.
CREATE TABLE IF NOT EXISTS llm_usage (
  day      TEXT PRIMARY KEY,           -- provider quota day, YYYY-MM-DD
  requests INTEGER NOT NULL DEFAULT 0,
  tokens   INTEGER NOT NULL DEFAULT 0,
  errors   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dlq (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id     TEXT NOT NULL DEFAULT '',
  stage      TEXT NOT NULL DEFAULT '',
  source     TEXT NOT NULL DEFAULT '',
  source_url TEXT NOT NULL DEFAULT '',
  payload    TEXT NOT NULL DEFAULT '',
  error      TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_dlq_created ON dlq(created_at);

CREATE TABLE IF NOT EXISTS run_log (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id       TEXT NOT NULL,
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  ingested     INTEGER NOT NULL DEFAULT 0,
  gated        INTEGER NOT NULL DEFAULT 0,
  extracted    INTEGER NOT NULL DEFAULT 0,
  duplicates   INTEGER NOT NULL DEFAULT 0,
  published    INTEGER NOT NULL DEFAULT 0,
  errors       INTEGER NOT NULL DEFAULT 0,
  llm_calls    INTEGER NOT NULL DEFAULT 0,
  outcome      TEXT NOT NULL DEFAULT 'ok',
  source_stats TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_run_started ON run_log(started_at);
"""


def now() -> str:
    return format_ts()


def since(days: int) -> str:
    """SQLite expression operand for 'N days ago' in our timestamp format."""
    return f"-{int(days)} days"


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection in true autocommit mode with sane pragmas."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=268435456")
    conn.execute("PRAGMA cache_size=-64000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Explicit BEGIN IMMEDIATE / COMMIT, rolling back on any exception."""
    if conn.in_transaction:
        conn.execute("SAVEPOINT predoc_nested_write")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK TO SAVEPOINT predoc_nested_write")
            conn.execute("RELEASE SAVEPOINT predoc_nested_write")
            raise
        conn.execute("RELEASE SAVEPOINT predoc_nested_write")
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


#: Columns added after the first release. ``CREATE TABLE IF NOT EXISTS`` does not
#: touch an existing table, so a database from an older version gets them here.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("listings", "deadline_note", "TEXT"),
    ("listings", "visa_note", "TEXT"),
    ("listings", "closed_reason", "TEXT"),
    ("listings", "closed_at", "TEXT"),
    ("listings", "last_checked_at", "TEXT"),
    ("listings", "department", "TEXT"),
    ("listings", "fields", "TEXT"),
    ("listings", "x_post_id", "TEXT"),
    ("listings", "salary_min", "REAL"),
    ("listings", "salary_max", "REAL"),
    ("listings", "salary_currency", "TEXT"),
    ("listings", "salary_period", "TEXT"),
    ("listings", "salary_raw", "TEXT"),
    ("listings", "tools_required", "TEXT DEFAULT '[]'"),
    ("listings", "tools_preferred", "TEXT DEFAULT '[]'"),
    ("listings", "min_degree", "TEXT"),
    ("listings", "degree_note", "TEXT"),
    ("listings", "start_term", "TEXT"),
    ("listings", "start_date", "TEXT"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, kind in _ADDED_COLUMNS:
        have = {
            row[1] if isinstance(row, (tuple, list)) else row["name"]
            for row in conn.execute(f"PRAGMA table_info({table})")
        }
        if column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


def init(db_path: str | Path) -> None:
    """Create or migrate the schema. Idempotent."""
    with closing(connect(db_path)) as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        with transaction(conn):
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )


class Database:
    """Thin, explicit data-access layer.

    Deliberately not an ORM. Every query is visible, every write is scoped to a
    transaction, and the object owns its connection so callers can use it as a
    context manager and be sure the handle closes.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.path = str(db_path)
        self.conn = connect(db_path)
        self._lock = threading.RLock()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.optimize()
            self.checkpoint()
        finally:
            self.conn.close()

    def optimize(self) -> None:
        """Run PRAGMA optimize to refresh query planner statistics."""
        try:
            self.conn.execute("PRAGMA optimize")
        except sqlite3.Error as exc:  # pragma: no cover - best effort
            _log.debug("pragma optimize failed: %s", exc)

    def checkpoint(self) -> None:
        """Fold the WAL back into the main database file.

        Must run before anything copies, commits or uploads the .db file.
        """
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error as exc:  # pragma: no cover - best effort
            _log.debug("wal_checkpoint failed: %s", exc)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialize writes on this Database connection with self._lock and transaction()."""
        with self._lock, transaction(self.conn):
            yield self.conn

    # -- meta -------------------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.transaction():
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # -- seen items -------------------------------------------------------
    def seen(self, url_hash: str) -> sqlite3.Row | None:
        return cast(sqlite3.Row | None, self.conn.execute(
            "SELECT * FROM seen_items WHERE url_hash=?", (url_hash,)
        ).fetchone())

    def mark_seen(
        self,
        url_hash: str,
        *,
        source: str,
        decision: str,
        reason: str = "",
        content_hash: str = "",
        listing_id: int | None = None,
    ) -> None:
        ts = now()
        with self.transaction():
            self.conn.execute(
                """
                INSERT INTO seen_items
                  (url_hash, source, decision, reason, content_hash, listing_id,
                   first_seen_at, last_seen_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(url_hash) DO UPDATE SET
                  decision=excluded.decision,
                  reason=excluded.reason,
                  content_hash=excluded.content_hash,
                  listing_id=COALESCE(excluded.listing_id, seen_items.listing_id),
                  last_seen_at=excluded.last_seen_at
                """,
                (url_hash, source, decision, reason, content_hash, listing_id, ts, ts),
            )

    def seen_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM seen_items").fetchone()[0])

    # -- listings ---------------------------------------------------------
    def listing_by_url_hash(self, url_hash: str) -> sqlite3.Row | None:
        return cast(sqlite3.Row | None, self.conn.execute(
            "SELECT * FROM listings WHERE url_hash=?", (url_hash,),
        ).fetchone())

    def listing_by_url(self, url: str) -> sqlite3.Row | None:
        """Find a listing by exact URL hash, apply_url, source_url, or alternate_sources."""
        if not url:
            return None
        from .urls import canonicalize_url, url_hash

        h = url_hash(url)
        canon = canonicalize_url(url)
        row = self.conn.execute(
            "SELECT * FROM listings WHERE url_hash=? OR apply_url=? OR source_url=? OR "
            "apply_url=? OR source_url=?",
            (h, url, url, canon, canon),
        ).fetchone()
        if row is not None:
            return cast(sqlite3.Row | None, row)
        return cast(sqlite3.Row | None, self.conn.execute(
            "SELECT * FROM listings WHERE alternate_sources LIKE ?",
            (f'%"{url}"%',),
        ).fetchone())

    def listing_by_identity(self, institution: str, title: str) -> sqlite3.Row | None:
        """Find an existing published listing by normalized institution and title."""
        inst = (institution or "").strip().lower()
        tit = (title or "").strip().lower()
        if not inst or not tit:
            return None
        return cast(sqlite3.Row | None, self.conn.execute(
            "SELECT * FROM listings WHERE LOWER(TRIM(institution))=? AND LOWER(TRIM(title))=? "
            "AND status='published' AND closed_at IS NULL",
            (inst, tit),
        ).fetchone())

    def listing(self, listing_id: int) -> sqlite3.Row | None:
        return cast(sqlite3.Row | None, self.conn.execute(
            "SELECT * FROM listings WHERE id=?", (listing_id,),
        ).fetchone())

    def insert_listing(self, values: dict[str, Any]) -> int:
        """Insert a listing in `pending` status. Returns the new row id.

        The row is written *before* the broadcast attempt so a crash between
        the two leaves a recoverable pending row rather than an untracked
        message in the channel.
        """
        columns = (
            "url_hash",
            "apply_url",
            "source_url",
            "source",
            "title",
            "institution",
            "principal_investigator",
            "country",
            "city",
            "is_remote",
            "duration_years",
            "deadline",
            "disciplines",
            "visa_sponsorship_status",
            "summary",
            "language",
            "model_confidence",
            "rule_score",
            "confidence",
            "signature",
            "first_seen_at",
            "last_seen_at",
            "status",
            "deadline_note",
            "visa_note",
            "department",
            "fields",
            "salary_min",
            "salary_max",
            "salary_currency",
            "salary_period",
            "salary_raw",
            "tools_required",
            "tools_preferred",
            "min_degree",
            "degree_note",
            "start_term",
            "start_date",
        )
        payload = {c: values.get(c) for c in columns}
        payload["first_seen_at"] = payload["first_seen_at"] or now()
        payload["last_seen_at"] = payload["last_seen_at"] or payload["first_seen_at"]
        payload["status"] = payload["status"] or "pending"
        payload["tools_required"] = payload["tools_required"] or "[]"
        payload["tools_preferred"] = payload["tools_preferred"] or "[]"
        placeholders = ",".join("?" for _ in columns)
        with self.transaction():
            cur = self.conn.execute(
                f"INSERT INTO listings ({','.join(columns)}) VALUES ({placeholders})",
                tuple(payload[c] for c in columns),
            )
            return int(cast(int, cur.lastrowid))

    def refresh_listing_facts(self, listing_id: int, values: dict[str, Any]) -> None:
        """Refresh extracted facts without rewriting identity or delivery history.

        The caller must establish that the new evidence describes the same
        vacancy. Reopening and cohort changes require separate lifecycle actions.
        """
        allowed = {
            "title", "institution", "principal_investigator", "country", "city",
            "is_remote", "duration_years", "deadline", "disciplines",
            "visa_sponsorship_status", "summary", "language", "model_confidence",
            "rule_score", "confidence", "signature", "deadline_note", "visa_note",
            "department", "fields", "salary_min", "salary_max", "salary_currency",
            "salary_period", "salary_raw", "tools_required", "tools_preferred",
            "min_degree", "degree_note", "start_term", "start_date",
        }
        invalid = set(values) - allowed
        if invalid:
            raise ValueError(f"non-fact listing fields: {', '.join(sorted(invalid))}")
        columns = sorted(values)
        assignments = [f"{column}=?" for column in columns] + ["last_seen_at=?"]
        with self.transaction():
            result = self.conn.execute(
                f"UPDATE listings SET {','.join(assignments)} WHERE id=?",
                (*[values[column] for column in columns], now(), listing_id),
            )
            if result.rowcount != 1:
                raise ValueError(f"listing {listing_id} does not exist")

    def mark_published(
        self,
        listing_id: int,
        message_id: int | None,
        x_post_id: str | None = None,
    ) -> None:
        with self.transaction():
            if x_post_id:
                self.conn.execute(
                    "UPDATE listings SET status='published', telegram_message_id=?, "
                    "x_post_id=?, published_at=? WHERE id=?",
                    (message_id, str(x_post_id), now(), listing_id),
                )
            else:
                self.conn.execute(
                    "UPDATE listings SET status='published', telegram_message_id=?, "
                    "published_at=? WHERE id=?",
                    (message_id, now(), listing_id),
                )

    def mark_x_published(self, listing_id: int, x_post_id: str | None) -> None:
        with self.transaction():
            self.conn.execute(
                "UPDATE listings SET x_post_id=? WHERE id=?",
                (str(x_post_id) if x_post_id else None, listing_id),
            )

    def mark_status(self, listing_id: int, status: str) -> None:
        with self.transaction():
            self.conn.execute("UPDATE listings SET status=? WHERE id=?", (status, listing_id))

    def touch_listing(self, listing_id: int) -> None:
        with self.transaction():
            self.conn.execute("UPDATE listings SET last_seen_at=? WHERE id=?", (now(), listing_id))

    def add_alternate_source(self, listing_id: int, source_url: str) -> None:
        with self.transaction():
            row = self.conn.execute(
                "SELECT alternate_sources FROM listings WHERE id=?", (listing_id,)
            ).fetchone()
            if row is None:
                return
            sources = json.loads(row["alternate_sources"] or "[]")
            if source_url and source_url not in sources:
                sources.append(source_url)
                self.conn.execute(
                    "UPDATE listings SET alternate_sources=?, last_seen_at=? WHERE id=?",
                    (json.dumps(sources), now(), listing_id),
                )

    def pending_listings(self) -> list[sqlite3.Row]:
        """Rows inserted but never confirmed as broadcast. Crash recovery.

        Publication status is authoritative: web-only publications intentionally
        have no Telegram message ID. Unpublished rows remain retryable when
        credentials become available.
        """
        return self.conn.execute(
            "SELECT * FROM listings WHERE status IN ('pending', 'unpublished') "
            "AND closed_at IS NULL AND expired_at IS NULL "
            "AND (deadline IS NULL OR deadline = '' OR "
            "     deadline >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-1 day')) ORDER BY id"
        ).fetchall()

    def recent_listings(self, days: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM listings WHERE first_seen_at >= "
            "strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?) ORDER BY first_seen_at DESC, id DESC",
            (since(days),),
        ).fetchall()

    def search_listings(
        self, query: str, *, active_only: bool = True, limit: int = 50
    ) -> list[sqlite3.Row]:
        """Search listings by keyword across title, institution, department, and summary."""
        q = (query or "").strip().lower()
        if not q:
            return []
        pattern = f"%{q}%"
        if active_only:
            return self.conn.execute(
                "SELECT * FROM listings WHERE status='published' AND expired_at IS NULL "
                "AND closed_at IS NULL AND (LOWER(title) LIKE ? OR LOWER(institution) LIKE ? "
                "OR LOWER(department) LIKE ? OR LOWER(summary) LIKE ?) "
                "ORDER BY first_seen_at DESC LIMIT ?",
                (pattern, pattern, pattern, pattern, limit),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM listings WHERE LOWER(title) LIKE ? OR LOWER(institution) LIKE ? "
            "OR LOWER(department) LIKE ? OR LOWER(summary) LIKE ? "
            "ORDER BY first_seen_at DESC LIMIT ?",
            (pattern, pattern, pattern, pattern, limit),
        ).fetchall()

    def active_listings(self) -> list[sqlite3.Row]:
        """Published, deadline not passed, not found filled/closed."""
        return self.conn.execute(
            "SELECT * FROM listings WHERE status='published' AND expired_at IS NULL "
            "AND closed_at IS NULL ORDER BY first_seen_at DESC"
        ).fetchall()

    def published_listings(self) -> list[sqlite3.Row]:
        """Everything ever sent, open or not (for /applied and re-filtering)."""
        return self.conn.execute(
            "SELECT * FROM listings WHERE status='published' ORDER BY id"
        ).fetchall()

    def listings_by_hash_prefix(self, prefix: str) -> list[sqlite3.Row]:
        """Telegram buttons carry a 16-character prefix of ``url_hash``."""
        return self.conn.execute(
            "SELECT * FROM listings WHERE substr(url_hash, 1, ?) = ?", (len(prefix), prefix)
        ).fetchall()

    def knows_url(self, url_hash_value: str) -> bool:
        """Has this posting URL been judged before (as a source or as an apply link)?"""
        if self.seen(url_hash_value) is not None:
            return True
        return self.listing_by_url_hash(url_hash_value) is not None

    def mark_closed(self, listing_id: int, reason: str) -> None:
        with self.transaction():
            self.conn.execute(
                "UPDATE listings SET closed_at=?, closed_reason=?, last_checked_at=? "
                "WHERE id=? AND closed_at IS NULL",
                (now(), reason[:200], now(), listing_id),
            )

    def mark_checked(self, listing_id: int) -> None:
        with self.transaction():
            self.conn.execute(
                "UPDATE listings SET last_checked_at=? WHERE id=?", (now(), listing_id)
            )

    def due_for_recheck(self, every_days: float, limit: int) -> list[sqlite3.Row]:
        """Open, published listings not checked for ``every_days`` (oldest first)."""
        offset = f"-{int(every_days * 24 * 60)} minutes"
        return self.conn.execute(
            "SELECT * FROM listings WHERE status='published' AND closed_at IS NULL "
            "AND expired_at IS NULL AND COALESCE(last_checked_at, first_seen_at) < "
            "strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?) "
            "ORDER BY COALESCE(last_checked_at, first_seen_at) LIMIT ?",
            (offset, limit),
        ).fetchall()

    def expire_past_deadline(self, grace_days: int = 1) -> int:
        """Mark listings whose deadline has passed. Returns rows affected."""
        with self.transaction():
            cur = self.conn.execute(
                "UPDATE listings SET expired_at=? WHERE expired_at IS NULL "
                "AND deadline IS NOT NULL AND deadline != '' "
                "AND deadline < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)",
                (now(), since(grace_days)),
            )
            return cur.rowcount or 0

    # -- LLM quota --------------------------------------------------------
    def llm_usage(self, day: str) -> tuple[int, int]:
        with self._lock:
            row = self.conn.execute(
                "SELECT requests, tokens FROM llm_usage WHERE day=?", (day,)
            ).fetchone()
            return (int(row["requests"]), int(row["tokens"])) if row else (0, 0)

    def record_llm_call(self, day: str, *, tokens: int = 0, error: bool = False) -> int:
        with self.transaction():
            self.conn.execute(
                "INSERT INTO llm_usage(day, requests, tokens, errors) VALUES(?,?,?,?) "
                "ON CONFLICT(day) DO UPDATE SET "
                "  requests = llm_usage.requests + 1,"
                "  tokens   = llm_usage.tokens + excluded.tokens,"
                "  errors   = llm_usage.errors + excluded.errors",
                (day, 1, tokens, 1 if error else 0),
            )
            row = self.conn.execute("SELECT requests FROM llm_usage WHERE day=?", (day,)).fetchone()
            return int(row["requests"])

    def reserve_llm_call(self, day: str, budget: int) -> bool:
        """One atomic check-and-increment, including across SQLite connections."""
        with self.transaction():
            if self.llm_usage(day)[0] >= budget:
                return False
            self.record_llm_call(day)
            return True

    def record_llm_result(self, day: str, *, tokens: int = 0, error: bool = False) -> None:
        with self.transaction():
            cur = self.conn.execute(
                "UPDATE llm_usage SET tokens=tokens+?, errors=errors+? WHERE day=?",
                (max(0, tokens), int(error), day),
            )
            if cur.rowcount != 1:
                raise ValueError(f"no model request reserved for quota day {day}")

    def export_llm_usage(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self.conn.execute(
                "SELECT day, requests, tokens, errors FROM llm_usage ORDER BY day DESC LIMIT 32"
            )]

    def import_llm_usage(self, records: Sequence[dict[str, Any]]) -> None:
        """Merge replayed cumulative counters monotonically, never add twice."""
        from datetime import date

        with self.transaction():
            for record in records:
                if not isinstance(record, dict):
                    raise ValueError("quota usage records must be objects")
                day = record.get("day")
                if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
                    raise ValueError("quota usage day must be YYYY-MM-DD")
                counts = [record.get(key) for key in ("requests", "tokens", "errors")]
                if any(type(value) is not int or value < 0 for value in counts):
                    raise ValueError("quota usage counters must be nonnegative integers")
                self.conn.execute(
                    "INSERT INTO llm_usage(day, requests, tokens, errors) VALUES(?,?,?,?) "
                    "ON CONFLICT(day) DO UPDATE SET "
                    "requests=MAX(llm_usage.requests, excluded.requests), "
                    "tokens=MAX(llm_usage.tokens, excluded.tokens), "
                    "errors=MAX(llm_usage.errors, excluded.errors)",
                    (day, *counts),
                )

    # -- HTTP cache -------------------------------------------------------
    def http_cache_get(self, url_hash: str) -> sqlite3.Row | None:
        return cast(sqlite3.Row | None, self.conn.execute(
            "SELECT * FROM http_cache WHERE url_hash=?", (url_hash,)
        ).fetchone())

    def http_cache_put(
        self,
        url_hash: str,
        url: str,
        *,
        etag: str | None,
        last_modified: str | None,
        body_hash: str | None,
        status: int,
    ) -> None:
        with self.transaction():
            self.conn.execute(
                "INSERT INTO http_cache(url_hash, url, etag, last_modified, body_hash, "
                "fetched_at, status) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(url_hash) DO UPDATE SET "
                "  etag=excluded.etag, last_modified=excluded.last_modified,"
                "  body_hash=COALESCE(excluded.body_hash, http_cache.body_hash),"
                "  fetched_at=excluded.fetched_at, status=excluded.status",
                (url_hash, url, etag, last_modified, body_hash, now(), status),
            )

    # -- DLQ and run log --------------------------------------------------
    def log_dlq(
        self,
        *,
        run_id: str,
        stage: str,
        source: str,
        source_url: str,
        payload: str,
        error: str,
    ) -> None:
        with self.transaction():
            self.conn.execute(
                "INSERT INTO dlq(run_id, stage, source, source_url, payload, error, "
                "created_at) VALUES(?,?,?,?,?,?,?)",
                (run_id, stage, source, source_url, payload[:4000], error[:2000], now()),
            )

    def dlq_for_run(self, run_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM dlq WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()

    def start_run(self, run_id: str) -> int:
        with self.transaction():
            cur = self.conn.execute(
                "INSERT INTO run_log(run_id, started_at) VALUES(?, ?)", (run_id, now())
            )
            return int(cast(int, cur.lastrowid))

    def finish_run(self, row_id: int, stats: dict[str, Any], source_stats: dict[str, Any]) -> None:
        with self.transaction():
            self.conn.execute(
                "UPDATE run_log SET finished_at=?, ingested=?, gated=?, extracted=?, "
                "duplicates=?, published=?, errors=?, llm_calls=?, outcome=?, "
                "source_stats=? WHERE id=?",
                (
                    now(),
                    stats.get("ingested", 0),
                    stats.get("gated", 0),
                    stats.get("extracted", 0),
                    stats.get("duplicates", 0),
                    stats.get("published", 0),
                    stats.get("errors", 0),
                    stats.get("llm_calls", 0),
                    stats.get("outcome", "ok"),
                    json.dumps(source_stats, sort_keys=True),
                    row_id,
                ),
            )

    def recent_runs(self, limit: int = 30) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM run_log ORDER BY started_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()

    def consecutive_empty_runs(self) -> int:
        """How many of the most recent completed runs published nothing."""
        count = 0
        for row in self.recent_runs(limit=30):  # health.json keeps 30 runs
            if row["finished_at"] is None:
                continue
            if (row["published"] or 0) > 0:
                break
            count += 1
        return count

    # -- maintenance ------------------------------------------------------
    def prune(self, *, dlq_days: int = 90, seen_days: int = 400, runs_keep: int = 180) -> None:
        with self.transaction():
            self.conn.execute(
                "DELETE FROM dlq WHERE created_at < strftime('%Y-%m-%dT%H:%M:%SZ','now',?)",
                (since(dlq_days),),
            )
            # Only forget seen items that never became listings; keeping the
            # rest is what stops a re-crawl from re-broadcasting old adverts.
            self.conn.execute(
                "DELETE FROM seen_items WHERE listing_id IS NULL AND "
                "last_seen_at < strftime('%Y-%m-%dT%H:%M:%SZ','now',?)",
                (since(seen_days),),
            )
            self.conn.execute(
                "DELETE FROM run_log WHERE id NOT IN "
                "(SELECT id FROM run_log ORDER BY id DESC LIMIT ?)",
                (runs_keep,),
            )

    def vacuum(self) -> None:
        self.conn.execute("VACUUM")

    def counts(self) -> dict[str, int]:
        q = self.conn.execute
        return {
            "listings": int(q("SELECT COUNT(*) FROM listings").fetchone()[0]),
            "published": int(
                q("SELECT COUNT(*) FROM listings WHERE status='published'").fetchone()[0]
            ),
            "pending": int(q("SELECT COUNT(*) FROM listings WHERE status='pending'").fetchone()[0]),
            "expired": int(
                q("SELECT COUNT(*) FROM listings WHERE expired_at IS NOT NULL").fetchone()[0]
            ),
            "closed": int(
                q("SELECT COUNT(*) FROM listings WHERE closed_at IS NOT NULL").fetchone()[0]
            ),
            "seen_items": int(q("SELECT COUNT(*) FROM seen_items").fetchone()[0]),
            "dlq": int(q("SELECT COUNT(*) FROM dlq").fetchone()[0]),
            "runs": int(q("SELECT COUNT(*) FROM run_log").fetchone()[0]),
        }

    def export_rows(self) -> list[dict[str, Any]]:
        """Every listing as a plain dict, for the JSONL state file."""
        rows = self.conn.execute("SELECT * FROM listings ORDER BY id").fetchall()
        out = []
        for row in rows:
            # sqlite3.Row: `in row` would test values, so .keys() is required here.
            record = {k: row[k] for k in row.keys() if k != "signature"}  # noqa: SIM118
            record["disciplines"] = json.loads(record.get("disciplines") or "[]")
            record["alternate_sources"] = json.loads(record.get("alternate_sources") or "[]")
            record["is_remote"] = bool(record.get("is_remote"))
            out.append(record)
        return out

    def import_rows(self, records: Sequence[dict[str, Any]]) -> int:
        """Restore IDs atomically; return actual inserts and surface invalid records."""
        inserted = 0
        allowed = {row["name"] for row in self.conn.execute("PRAGMA table_info(listings)")}
        with self.transaction():
            for record in records:
                data = dict(record)
                unknown = set(data) - allowed
                if unknown:
                    raise ValueError(f"unknown listing columns: {sorted(unknown)}")
                if "id" in data and (
                    type(data["id"]) is not int or data["id"] <= 0
                ):
                    raise ValueError("listing id must be a positive integer")
                if not isinstance(data.get("url_hash"), str) or not data["url_hash"]:
                    raise ValueError("listing url_hash must be a nonempty string")
                data["disciplines"] = json.dumps(data.get("disciplines") or [])
                data["alternate_sources"] = json.dumps(data.get("alternate_sources") or [])
                data["is_remote"] = int(bool(data.get("is_remote")))
                existing = self.listing_by_url_hash(data["url_hash"])
                if existing is not None and "id" in data and existing["id"] != data["id"]:
                    raise ValueError("listing URL has conflicting durable IDs")
                columns = list(data)
                placeholders = ",".join("?" for _ in columns)
                cur = self.conn.execute(
                    f"INSERT INTO listings ({','.join(columns)}) "
                    f"VALUES ({placeholders}) ON CONFLICT(url_hash) DO NOTHING",
                    tuple(data[c] for c in columns),
                )
                inserted += cur.rowcount
        return inserted

    # -- committed state for tables other than listings -----------------------
    _SEEN_EXPORT = ("url_hash", "source", "decision", "reason", "content_hash", "first_seen_at")

    def export_seen(self) -> list[dict[str, Any]]:
        """Export judgments with listing URL keys for durable recovery links."""
        rows = self.conn.execute(
            "SELECT seen_items.*, listings.url_hash AS listing_url_hash "
            "FROM seen_items LEFT JOIN listings ON listings.id=seen_items.listing_id "
            "ORDER BY seen_items.first_seen_at, seen_items.url_hash"
        ).fetchall()
        return [{k: row[k] for k in (*self._SEEN_EXPORT, "listing_url_hash")} for row in rows]

    def import_seen(self, records: Sequence[dict[str, Any]]) -> int:
        inserted = 0
        with self.transaction():
            for record in records:
                for field in ("url_hash", "decision"):
                    if not isinstance(record.get(field), str) or not record[field]:
                        raise ValueError(f"seen record requires nonempty {field}")
                listing_id = None
                if record.get("listing_url_hash"):
                    listing = self.listing_by_url_hash(record["listing_url_hash"])
                    if listing is None:
                        raise ValueError("seen record references a missing listing")
                    listing_id = listing["id"]
                first = record.get("first_seen_at") or now()
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO seen_items(url_hash, source, decision, reason, "
                    "content_hash, first_seen_at, last_seen_at, listing_id) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        record["url_hash"],
                        record.get("source") or "",
                        record["decision"],
                        (record.get("reason") or "")[:200],
                        record.get("content_hash") or "",
                        first,
                        first,
                        listing_id,
                    ),
                )
                inserted += cur.rowcount or 0
        return inserted

    def import_runs(self, runs: Sequence[dict[str, Any]]) -> int:
        """Rebuild ``run_log`` from docs/data/health.json, oldest first.

        Without this every CI run starts with an empty run log, so "N quiet runs
        in a row" and "source failing N runs in a row" could never be detected.
        """
        inserted = 0
        with self.transaction():
            for run in sorted(runs, key=lambda r: r.get("started_at") or ""):
                if not run.get("run_id") or not run.get("started_at"):
                    continue
                self.conn.execute(
                    "INSERT INTO run_log(run_id, started_at, finished_at, ingested, gated, "
                    "extracted, duplicates, published, errors, llm_calls, outcome, source_stats) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        run["run_id"],
                        run["started_at"],
                        run.get("finished_at"),
                        run.get("ingested", 0),
                        run.get("gated", 0),
                        run.get("extracted", 0),
                        run.get("duplicates", 0),
                        run.get("published", 0),
                        run.get("errors", 0),
                        run.get("llm_calls", 0),
                        run.get("outcome", "ok"),
                        json.dumps(run.get("source_stats") or {}, sort_keys=True),
                    ),
                )
                inserted += 1
        return inserted

    def source_failure_streaks(self, limit: int = 30) -> dict[str, int]:
        """For each source: how many of the latest finished runs in a row it failed.

        A run "failed" for a source when the source errored, or fetched fine but
        returned nothing although it is not marked ``may_be_empty``.
        """
        streaks: dict[str, int] = {}
        closed: set[str] = set()
        for row in self.recent_runs(limit=limit):
            if row["finished_at"] is None:
                continue
            try:
                stats = json.loads(row["source_stats"] or "{}")
            except ValueError:
                continue
            for name, data in stats.items():
                if name in closed or not isinstance(data, dict):
                    continue
                if _source_failed(data):
                    streaks[name] = streaks.get(name, 0) + 1
                else:
                    closed.add(name)
                    streaks.setdefault(name, 0)
        return streaks


def _source_failed(data: dict[str, Any]) -> bool:
    if data.get("skipped"):
        return False
    if data.get("ok") is False:
        return True
    items = data.get("items", 0) or 0
    if data.get("errors"):
        return True
    if items == 0 and data.get("fetched") and not data.get("unchanged"):
        return not data.get("may_be_empty", False)
    return False
