"""Inline buttons: ✅ interested · ❌ not for me · 📝 applied (tap again to undo)."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .feedback import APPLIED, CODE_BY_STATUS, ID_PREFIX, INVALID, STATUS_BY_CODE, VALID

__all__ = ["LEGEND", "feedback_row", "parse_callback", "rebuild"]

LEGEND = "Buttons: ✅ interested · ❌ not for me (hides it) · 📝 applied. Tap again to undo."
_ORDER = (VALID, INVALID, APPLIED)
_ICON = {VALID: "✅", INVALID: "❌", APPLIED: "📝"}
_WORD = {VALID: "Interested", INVALID: "Not for me", APPLIED: "Applied"}


def feedback_row(
    url_hash: str, status: str | None, number: int | None = None
) -> list[dict[str, str]]:
    """Numbered ``[✅ 3] [❌ 3] [📝 3]`` in lists, worded buttons on a single card.

    The active choice gets a dot: ``[• 📝 3]``.
    """
    row = []
    for st in _ORDER:
        label = f"{_ICON[st]} {number}" if number else f"{_ICON[st]} {_WORD[st]}"
        if st == status:
            label = "• " + label
        data = f"fb|{CODE_BY_STATUS[st]}|{url_hash[:ID_PREFIX]}"
        row.append({"text": label, "callback_data": data})
    return row


def parse_callback(data: str | None) -> tuple[str, str] | None:
    """``'fb|a|0123abcd...'`` -> ``('a', '0123abcd...')``."""
    parts = (data or "").split("|")
    if len(parts) == 3 and parts[0] == "fb" and parts[1] in STATUS_BY_CODE and parts[2]:
        return parts[1], parts[2]
    return None


def rebuild(
    markup: dict[str, Any] | None, status_of: Callable[[str], str | None]
) -> dict[str, Any] | None:
    """Redraw a keyboard Telegram sent back with a tap, using the current marks."""
    if not markup:
        return None
    rows = []
    for row in markup.get("inline_keyboard", []):
        parsed = next((p for p in (parse_callback(b.get("callback_data")) for b in row) if p), None)
        if not parsed:
            rows.append(row)
            continue
        match = re.search(r"\d+", row[0].get("text", ""))
        prefix = parsed[1]
        rows.append(feedback_row(prefix, status_of(prefix), int(match.group()) if match else None))
    return {"inline_keyboard": rows}
