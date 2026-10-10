"""Your own marks on positions (✅ interested, ❌ not for me, 📝 applied).

Marks are keyed by the listing's ``url_hash`` (stable across journal restores,
unlike the SQLite row id). Only the Telegram-sync job writes this state; the
daily run only reads it, so the two workflows never overwrite each other's work.

Privacy: the repository that runs the pipeline may be public, and an *applied*
mark is personal. When ``FEEDBACK_ENCRYPTION_KEY`` is set the marks are stored
only as a Fernet-encrypted file (``feedback.enc`` beside the configured path);
no plaintext file is written. Without a key the plaintext file is written for
local use and is gitignored; scheduled workflows stage only the encrypted file.

Integrity: absent state is an empty store, but malformed or wrong-shaped state
is never treated as empty. The damaged file is copied aside for inspection and
:class:`StateCorruptError` stops the operation, so a bad write can neither
erase marks nor reset the Telegram update cursor.
"""

from __future__ import annotations

import builtins
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

__all__ = [
    "VALID", "INVALID", "APPLIED", "STATUS_BY_CODE", "CODE_BY_STATUS", "ID_PREFIX",
    "FeedbackStore", "StateCorruptError", "load_state", "load_chat_state", "save_state",
    "generate_key", "encrypted_path",
]

VALID, INVALID, APPLIED = "valid", "invalid", "applied"
STATUS_BY_CODE = {"v": VALID, "x": INVALID, "a": APPLIED}
CODE_BY_STATUS = {v: k for k, v in STATUS_BY_CODE.items()}
ID_PREFIX = 16  # characters of url_hash carried in a button (Telegram allows 64 bytes)
MAX_REMEMBERED_CALLBACKS = 500


class StateCorruptError(RuntimeError):
    """Saved personal state exists but cannot be trusted. The original is preserved."""

    def __init__(self, path: Path, reason: str, preserved: Path | None = None):
        where = f" (copy kept at {preserved})" if preserved else ""
        super().__init__(f"{path}: {reason}{where}. Repair or restore the file; "
                         "it has not been modified or replaced.")
        self.path, self.reason, self.preserved = path, reason, preserved


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _preserve(path: Path) -> Path | None:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = path.with_name(f"{path.name}.corrupt-{stamp}")
    try:
        shutil.copy2(path, target)
    except OSError:
        return None
    return target


def _corrupt(path: Path, reason: str) -> StateCorruptError:
    return StateCorruptError(path, reason, _preserve(path))


def generate_key() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode("ascii")


def encrypted_path(path: str | Path) -> Path:
    return Path(path).with_suffix(".enc")


def _fernet(key: str) -> Fernet:
    from cryptography.fernet import Fernet
    try:
        return Fernet(key.strip().encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise ValueError("FEEDBACK_ENCRYPTION_KEY is not a valid Fernet key; "
                         "create one with `predoc-pipeline feedback-key`") from exc


def _read_json(path: Path, *, key: str | None = None) -> dict[str, Any] | None:
    """None when the file is absent; raises StateCorruptError when unusable."""
    if not path.exists():
        return None
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise StateCorruptError(path, f"unreadable: {exc}") from exc
    if key:
        from cryptography.fernet import InvalidToken
        try:
            raw = _fernet(key).decrypt(raw)
        except InvalidToken as exc:
            raise _corrupt(path, "cannot be decrypted with the configured key "
                                 "(wrong key or damaged file)") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise _corrupt(path, f"malformed JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise _corrupt(path, "top-level value is not an object")
    return data


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


def _dump(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _validate_feedback(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    marks = data.get("marks", {})
    if not isinstance(marks, dict):
        raise _corrupt(path, "'marks' is not an object")
    for url_hash, mark in marks.items():
        if not isinstance(mark, dict) or mark.get("status") not in STATUS_BY_CODE.values():
            raise _corrupt(path, f"invalid mark for {url_hash!r}")
    callbacks = data.get("callbacks", [])
    if not isinstance(callbacks, list) or not all(isinstance(c, str) for c in callbacks):
        raise _corrupt(path, "'callbacks' is not a list of strings")
    data["marks"], data["callbacks"] = marks, callbacks
    return data


class FeedbackStore:
    def __init__(self, path: str | Path, *, key: str | None = None):
        self.path = Path(path)
        self.key = (key or "").strip() or None
        if self.key:
            _fernet(self.key)  # fail early with an actionable message
        self._legacy_plain: Path | None = None
        if self.key:
            self.store_path = encrypted_path(self.path)
            data = _read_json(self.store_path, key=self.key)
            if data is None:  # one-time migration from a plaintext file
                data = _read_json(self.path)
                if data is not None:
                    self._legacy_plain = self.path
        else:
            if encrypted_path(self.path).exists():
                raise StateCorruptError(
                    encrypted_path(self.path),
                    "encrypted feedback requires FEEDBACK_ENCRYPTION_KEY; "
                    "restore the original key before continuing",
                )
            self.store_path = self.path
            data = _read_json(self.path)
        self.data = _validate_feedback(self.store_path if data is not None else self.path,
                                       data or {})
        self._dirty = self._legacy_plain is not None

    @classmethod
    def from_settings(cls, settings: Any) -> FeedbackStore:
        return cls(settings.feedback_path, key=getattr(settings, "feedback_encryption_key", ""))

    @property
    def marks(self) -> dict[str, dict[str, Any]]:
        return cast(dict[str, dict[str, Any]], self.data["marks"])

    def status(self, url_hash: str) -> str | None:
        return (self.marks.get(url_hash) or {}).get("status")

    def marked_at(self, url_hash: str) -> str | None:
        return (self.marks.get(url_hash) or {}).get("at")

    def set(self, url_hash: str, status: str | None, **info: Any) -> None:
        self._dirty = True
        if status is None:
            self.marks.pop(url_hash, None)
            return
        self.marks[url_hash] = {"status": status, "at": _now(),
                                **{k: v for k, v in info.items() if v}}

    def with_status(self, status: str) -> builtins.set[str]:
        return {h for h, v in self.marks.items() if v.get("status") == status}

    @property
    def hidden(self) -> builtins.set[str]:
        return self.with_status(INVALID)

    def callback_seen(self, callback_id: str | None) -> bool:
        return bool(callback_id) and callback_id in self.data["callbacks"]

    def remember_callback(self, callback_id: str | None) -> None:
        """Recorded in the same atomic write as the mark it produced, so a replayed
        tap (a retried getUpdates batch) cannot toggle the mark a second time."""
        if not callback_id or callback_id in self.data["callbacks"]:
            return
        self.data["callbacks"].append(str(callback_id))
        del self.data["callbacks"][:-MAX_REMEMBERED_CALLBACKS]
        self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        payload = _dump(self.data)
        if self.key:
            payload = _fernet(self.key).encrypt(payload)
        _write_atomic(self.store_path, payload)
        if self._legacy_plain is not None:
            self._legacy_plain.unlink(missing_ok=True)  # never leave marks in plaintext
            self._legacy_plain = None
        self._dirty = False


def load_state(path: str | Path) -> dict[str, Any]:
    """Strict: {} only when the file is absent."""
    return _read_json(Path(path)) or {}


def load_chat_state(path: str | Path) -> dict[str, Any]:
    """Bot cursor state with a validated offset."""
    p = Path(path)
    state = load_state(p)
    offset = state.get("offset")
    if offset is not None and (isinstance(offset, bool) or not isinstance(offset, int)
                               or offset < 0):
        raise _corrupt(p, f"invalid update offset {offset!r}")
    return state


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    _write_atomic(Path(path), _dump(state))
