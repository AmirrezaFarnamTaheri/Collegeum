"""Durable segment acknowledgements and submission intents for X threads.

An intent survives a crash before the acknowledgement can be recorded. Such a
segment must be reconciled with X before retrying; automatic replay is unsafe.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeGuard


class ThreadStateError(RuntimeError):
    """Invalid state or another publisher already claimed this segment."""

    def __init__(self, message: str, *, state: ThreadState | None = None) -> None:
        super().__init__(message)
        self.state = state


@dataclass(frozen=True)
class ThreadState:
    key: str
    fingerprint: str
    count: int
    ids: tuple[str, ...]
    pending: bool


def valid_post_id(value: object) -> TypeGuard[str]:
    return (isinstance(value, str) and 1 <= len(value) <= 20 and value.isascii()
            and value.isdecimal() and value[0] != '0' and int(value) < 2**64)


class XThreadJournal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.journal_path = self.path.with_suffix('.ndjson')

    def _restore(self, connection: sqlite3.Connection) -> None:
        if not self.journal_path.exists():
            return
        records: dict[str, ThreadState] = {}
        keys = set()
        for line in self.journal_path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if (not isinstance(record, dict) or type(record.get('version')) is not int
                        or record['version'] != 1 or not isinstance(record.get('ids'), list)):
                    raise ValueError('Unsupported X journal record')
                key, fingerprint = record['key'], record['fingerprint']
                if any(not isinstance(value, str) or len(value) != 64
                       or any(c not in '0123456789abcdef' for c in value)
                       for value in (key, fingerprint)) or key in keys:
                    raise ValueError('Invalid X journal identity')
                state = self._state(record)
                keys.add(key)
                records[key] = state
            except (ValueError, TypeError, KeyError, ThreadStateError) as error:
                raise ThreadStateError('Malformed durable X thread journal; preserved unchanged') \
                    from error
        if not records:
            raise ThreadStateError('Empty durable X thread journal; preserved unchanged')
        for row in connection.execute('SELECT * FROM x_threads'):
            cached = self._state(row)
            saved = records.get(cached.key)
            if saved is not None:
                if (cached.fingerprint != saved.fingerprint or cached.count != saved.count
                        or cached.ids[:len(saved.ids)] != saved.ids[:len(cached.ids)]):
                    raise ThreadStateError('Conflicting X journal/cache progress; reconcile first',
                                           state=cached)
                if len(cached.ids) < len(saved.ids):
                    continue
                if len(cached.ids) == len(saved.ids):
                    cached = ThreadState(cached.key, cached.fingerprint, cached.count,
                                         cached.ids, cached.pending or saved.pending)
            records[cached.key] = cached
        connection.execute('DELETE FROM x_threads')
        connection.executemany('INSERT INTO x_threads VALUES (?, ?, ?, ?, ?)', [
            (state.key, state.fingerprint, state.count, json.dumps(state.ids), int(state.pending))
            for state in records.values()
        ])

    def _export(self, connection: sqlite3.Connection) -> None:
        temporary = self.journal_path.with_suffix('.ndjson.tmp')
        try:
            with temporary.open('w', encoding='utf-8', newline='\n') as stream:
                for row in connection.execute('SELECT * FROM x_threads ORDER BY key'):
                    state = self._state(row)
                    stream.write(json.dumps({
                        'version': 1, 'key': state.key, 'fingerprint': state.fingerprint,
                        'count': state.count, 'ids': state.ids, 'pending': int(state.pending),
                    }, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.journal_path)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('''CREATE TABLE IF NOT EXISTS x_threads (
                key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                count INTEGER NOT NULL, ids TEXT NOT NULL, pending INTEGER NOT NULL
            )''')
            connection.commit()
            connection.execute('BEGIN IMMEDIATE')
            self._restore(connection)
            yield connection
            self._export(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _state(row: sqlite3.Row | dict[str, Any]) -> ThreadState:
        try:
            ids = json.loads(row['ids']) if isinstance(row['ids'], str) else row['ids']
        except (ValueError, TypeError) as error:
            raise ThreadStateError('Malformed X thread acknowledgement journal') from error
        if (not isinstance(ids, list) or any(not valid_post_id(value) for value in ids)
                or len(set(ids)) != len(ids) or type(row['count']) is not int
                or row['count'] < 1 or len(ids) > row['count']
                or type(row['pending']) is not int or row['pending'] not in (0, 1)
                or (row['pending'] and len(ids) == row['count'])):
            raise ThreadStateError('Invalid X thread acknowledgement journal')
        return ThreadState(row['key'], row['fingerprint'], row['count'], tuple(ids),
                           bool(row['pending']))

    def prepare(self, key: str, fingerprint: str, count: int) -> ThreadState:
        with self._connection() as connection:
            row = connection.execute('SELECT * FROM x_threads WHERE key=?', (key,)).fetchone()
            if row is None:
                connection.execute('INSERT INTO x_threads VALUES (?, ?, ?, ?, 0)',
                                   (key, fingerprint, count, '[]'))
                return ThreadState(key, fingerprint, count, (), False)
            state = self._state(row)
            if state.fingerprint != fingerprint or state.count != count:
                raise ThreadStateError(
                    'Thread content changed; reconcile the existing thread first', state=state)
            return state

    def _update(self, state: ThreadState, ids: tuple[str, ...], pending: bool) -> ThreadState:
        with self._connection() as connection:
            row = connection.execute('SELECT * FROM x_threads WHERE key=?', (state.key,)).fetchone()
            current = self._state(row) if row is not None else None
            if current != state:
                raise ThreadStateError('X thread state changed; another publisher may be active',
                                       state=current)
            connection.execute('UPDATE x_threads SET ids=?, pending=? WHERE key=?',
                               (json.dumps(ids), int(pending), state.key))
        return ThreadState(state.key, state.fingerprint, state.count, ids, pending)

    def claim(self, state: ThreadState) -> ThreadState:
        if state.pending or len(state.ids) >= state.count:
            raise ThreadStateError('X thread has no safely retryable segment')
        return self._update(state, state.ids, True)

    def acknowledge(self, state: ThreadState, post_id: str) -> ThreadState:
        if not state.pending or not valid_post_id(post_id) or post_id in state.ids:
            raise ThreadStateError('Invalid X segment acknowledgement')
        return self._update(state, (*state.ids, post_id), False)

    def reject(self, state: ThreadState) -> ThreadState:
        if not state.pending:
            raise ThreadStateError('No X segment submission to reject')
        return self._update(state, state.ids, False)

    def resolve(self, key: str, *, post_id: str | None = None,
                confirmed_not_created: bool = False) -> ThreadState:
        """Record an externally verified outcome; this does not query or write X."""
        if (post_id is None) == (not confirmed_not_created):
            raise ValueError('Supply a verified post ID or confirm that no post was created')
        with self._connection() as connection:
            row = connection.execute('SELECT * FROM x_threads WHERE key=?', (key,)).fetchone()
            if row is None:
                raise ThreadStateError('Unknown X thread')
            state = self._state(row)
        if not state.pending:
            raise ThreadStateError('X thread does not need outcome reconciliation')
        return self.acknowledge(state, post_id) if post_id is not None else self.reject(state)
