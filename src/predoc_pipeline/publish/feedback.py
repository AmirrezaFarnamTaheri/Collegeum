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
from datetime import UTC, datetime, timedelta
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
MAX_SUBSCRIBERS = 1000
MAX_CALLBACK_IDS = 65536  # above the maximum ordinary updates processed in 24h


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
    subscribers = data.get("subscribers", {})
    if not isinstance(subscribers, dict):
        raise _corrupt(path, "'subscribers' must be an object")
    for chat_id, member in subscribers.items():
        if (not isinstance(chat_id, str) or not chat_id.isascii() or
                not chat_id.isdecimal() or int(chat_id) <= 0 or
                not isinstance(member, dict)):
            raise _corrupt(path, "invalid subscriber identity")
        for field in ("topics", "scopes", "deliveries"):
            value = member.get(field, {})
            if not isinstance(value, dict):
                raise _corrupt(path, f"subscriber {chat_id}: {field} is not an object")
            member.setdefault(field, {})
        for field in ("topics", "scopes"):
            if not all(isinstance(k, str) and isinstance(v, str)
                       for k, v in member[field].items()):
                raise _corrupt(path, f"subscriber {chat_id}: invalid {field}")
        if not isinstance(member.get("paused", False), bool):
            raise _corrupt(path, f"subscriber {chat_id}: paused must be a boolean")
        if member.get("language", "en") not in ("en", "fa"):
            raise _corrupt(path, f"subscriber {chat_id}: invalid language")
        member.setdefault("paused", False)
        member.setdefault("language", "en")
        for delivery in member["deliveries"].values():
            if not isinstance(delivery, dict) or delivery.get("state") not in (
                "sending", "sent", "uncertain", "rejected",
            ) or not isinstance(delivery.get("at"), str):
                raise _corrupt(path, f"subscriber {chat_id}: invalid delivery journal")
    ops = data.get("ops", {"paused": False, "audit": []})
    if not isinstance(ops, dict) or not isinstance(ops.get("paused", False), bool):
        raise _corrupt(path, "'ops' must include a boolean paused flag")
    audit = ops.get("audit", [])
    if not isinstance(audit, list) or not all(
        isinstance(event, dict) and isinstance(event.get("action"), str)
        for event in audit
    ):
        raise _corrupt(path, "invalid operation audit history")
    ops.setdefault("paused", False)
    ops.setdefault("audit", [])
    cursor = data.get("delivery_cursor", "")
    if not isinstance(cursor, str):
        raise _corrupt(path, "invalid private delivery cursor")
    data["ops"], data["delivery_cursor"] = ops, cursor
    data["marks"], data["callbacks"], data["subscribers"] = marks, callbacks, subscribers
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

    @property
    def subscribers(self) -> dict[str, dict[str, Any]]:
        return cast(dict[str, dict[str, Any]], self.data["subscribers"])

    def subscriber(self, chat_id: int | str) -> dict[str, Any] | None:
        return self.subscribers.get(str(chat_id))

    def _member(self, chat_id: int) -> dict[str, Any]:
        if type(chat_id) is not int or chat_id <= 0:
            raise ValueError("invalid private chat ID")
        if (str(chat_id) not in self.subscribers
                and len(self.subscribers) >= MAX_SUBSCRIBERS):
            raise ValueError("subscriber capacity reached")
        return self.subscribers.setdefault(str(chat_id), {
            "topics": {}, "scopes": {}, "deliveries": {},
            "paused": False, "language": "en",
        })

    def toggle_subscription(self, chat_id: int, kind: str, option: str) -> bool:
        """Explicit private-chat opt-in. Return whether option is enabled."""
        from .subscriptions import CAREER_SCOPES, TOPICS

        if kind not in ("topics", "scopes"):
            raise ValueError("invalid subscription operation")
        if option not in (TOPICS if kind == "topics" else CAREER_SCOPES):
            raise ValueError("unknown subscription option")
        selections: dict[str, str] = self._member(chat_id)[kind]
        if option in selections:
            del selections[option]
            enabled = False
        else:
            selections[option] = _now()
            enabled = True
        self._dirty = True
        return enabled

    def set_topics_group(self, chat_id: int, group: str, enabled: bool) -> bool:
        """Apply an explicitly tapped group action, preserving prior opt-in dates."""
        from .ui import ACADEMIC, CAREERS

        if type(enabled) is not bool or group not in ("academic", "careers"):
            raise ValueError("invalid bulk subscription action")
        topics = self._member(chat_id)["topics"]
        selected = ACADEMIC if group == "academic" else CAREERS
        changed = False
        for key in selected:
            if enabled and key not in topics:
                topics[key] = _now()
                changed = True
            elif not enabled and key in topics:
                del topics[key]
                changed = True
        if changed:
            self._dirty = True
        return changed

    def set_paused(self, chat_id: int, paused: bool) -> bool:
        if type(paused) is not bool:
            raise ValueError("invalid pause state")
        member = self._member(chat_id)
        if member["paused"] == paused:
            return False
        member["paused"] = paused
        self._dirty = True
        return True

    def set_language(self, chat_id: int, language: str) -> bool:
        if language not in ("en", "fa"):
            raise ValueError("unsupported language")
        member = self._member(chat_id)
        if member["language"] == language:
            return False
        member["language"] = language
        self._dirty = True
        return True

    def prune_deliveries(self, *, days: int = 45) -> int:
        """Discard old confirmed receipts, never unresolved/uncertain sends.

        Incoming academic matches are bounded to fourteen days; career
        records are bounded to twenty-one. Keeping 45 days of successful
        receipts prevents duplicate sends without unbounded growth.
        """
        threshold = datetime.now(UTC) - timedelta(days=days)
        removed = 0
        for member in self.subscribers.values():
            receipts = member["deliveries"]
            for key, record in list(receipts.items()):
                if record["state"] != "sent":
                    continue
                try:
                    when = datetime.fromisoformat(record["at"].replace("Z", "+00:00"))
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=UTC)
                except (ValueError, TypeError):
                    continue  # never delete an invalid/unknown receipt automatically
                if when < threshold:
                    del receipts[key]
                    removed += 1
        if removed:
            self._dirty = True
        return removed

    def remove_subscriber(self, chat_id: int) -> bool:
        if self.subscribers.pop(str(chat_id), None) is None:
            return False
        self._dirty = True
        return True

    def reserve_delivery(self, chat_id: int, key: str) -> bool:
        """Write a send intent before network I/O to suppress crash replays."""
        member = self.subscriber(chat_id)
        if member is None or key in member["deliveries"]:
            return False
        member["deliveries"][key] = {"state": "sending", "at": _now()}
        self._dirty = True
        return True

    def finish_delivery(
        self, chat_id: int, key: str, *,
        message_id: int | None = None, uncertain: bool = False,
    ) -> None:
        member = self.subscriber(chat_id)
        if member is None or key not in member["deliveries"]:
            raise ValueError("delivery intent not found")
        member["deliveries"][key] = {
            "state": "uncertain" if uncertain else "sent",
            "at": _now(),
            **({"message_id": message_id} if message_id is not None else {}),
        }
        self._dirty = True

    def reject_delivery(self, chat_id: int, key: str, *, status: int) -> None:
        """Remember permanent API validation failures until reviewed.

        Replaying a known 400 every half hour cannot repair malformed HTML.
        """
        member = self.subscriber(chat_id)
        if member is None or key not in member["deliveries"]:
            raise ValueError("delivery intent not found")
        member["deliveries"][key] = {
            "state": "rejected", "at": _now(), "status": status,
        }
        self._dirty = True

    def cancel_delivery(self, chat_id: int, key: str) -> None:
        """Only call when an explicit API response proves no message was sent."""
        member = self.subscriber(chat_id)
        if member is not None and key in member["deliveries"]:
            del member["deliveries"][key]
            self._dirty = True

    def resolve_delivery(
        self, chat_id: int, key: str, *,
        confirmed_sent: bool = False, confirmed_absent: bool = False,
        message_id: int | None = None,
    ) -> None:
        if confirmed_sent == confirmed_absent:
            raise ValueError("Exactly one verified delivery outcome is required")
        if confirmed_sent and (type(message_id) is not int or message_id <= 0):
            raise ValueError("A verified positive Telegram message ID is required")
        if confirmed_absent and message_id is not None:
            raise ValueError("Do not supply a message ID for confirmed non-delivery")
        member = self.subscriber(chat_id)
        if member is None or key not in member["deliveries"]:
            raise ValueError("Unknown subscriber delivery")
        existing = member["deliveries"][key]
        if existing["state"] == "sent":
            if confirmed_sent and existing.get("message_id") == message_id:
                return
            raise ValueError("Cannot overwrite a confirmed delivery")
        if confirmed_sent and existing["state"] == "rejected":
            raise ValueError("Telegram explicitly rejected that delivery")
        if confirmed_sent:
            self.finish_delivery(chat_id, key, message_id=message_id)
        else:
            self.cancel_delivery(chat_id, key)

    def wants_career(self, scope: str) -> bool:
        from .subscriptions import CAREER_TOPICS
        return any(
            scope in member["scopes"]
            and any(topic in member["topics"] for topic in CAREER_TOPICS)
            for member in self.subscribers.values()
        )

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
        # A cursor reset can replay even an old callback. Pruning by a fixed
        # count would allow that replay to toggle an existing mark again.
        # Retain processed IDs until an explicit audited state compaction.
        self.data["callbacks"].append(str(callback_id))
        # Telegram only retains unconsumed updates for up to 24 hours. Keep
        # ample replay headroom while bounding retained callback identifiers.
        if len(self.data["callbacks"]) > MAX_CALLBACK_IDS:
            del self.data["callbacks"][:-MAX_CALLBACK_IDS]
        self._dirty = True

    def mark_dirty(self) -> None:
        """Mark mutations made to the admin operation record for persistence."""
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
