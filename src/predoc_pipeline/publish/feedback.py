"""Your own marks on positions (✅ interested, ❌ not for me, 📝 applied).

Stored in ``data/feedback.json`` keyed by the listing's ``url_hash`` (stable
across journal restores, unlike the SQLite row id). Only the Telegram-sync job
writes this file; the daily run only reads it, so the two workflows never
overwrite each other's work.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "VALID", "INVALID", "APPLIED", "STATUS_BY_CODE", "CODE_BY_STATUS", "ID_PREFIX",
    "FeedbackStore", "load_state", "save_state",
]

VALID, INVALID, APPLIED = "valid", "invalid", "applied"
STATUS_BY_CODE = {"v": VALID, "x": INVALID, "a": APPLIED}
CODE_BY_STATUS = {v: k for k, v in STATUS_BY_CODE.items()}
ID_PREFIX = 16  # characters of url_hash carried in a button (Telegram allows 64 bytes)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


class FeedbackStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = _read_json(self.path)
        self.data.setdefault("marks", {})

    @property
    def marks(self) -> dict[str, dict[str, Any]]:
        return self.data["marks"]

    def status(self, url_hash: str) -> str | None:
        return (self.marks.get(url_hash) or {}).get("status")

    def marked_at(self, url_hash: str) -> str | None:
        return (self.marks.get(url_hash) or {}).get("at")

    def set(self, url_hash: str, status: str | None, **info: Any) -> None:
        if status is None:
            self.marks.pop(url_hash, None)
            return
        self.marks[url_hash] = {"status": status, "at": _now(),
                                **{k: v for k, v in info.items() if v}}

    def with_status(self, status: str) -> set[str]:
        return {h for h, v in self.marks.items() if v.get("status") == status}

    @property
    def hidden(self) -> set[str]:
        return self.with_status(INVALID)

    def save(self) -> None:
        _write_json(self.path, self.data)


def load_state(path: str | Path) -> dict[str, Any]:
    return _read_json(Path(path))


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    _write_json(Path(path), state)
