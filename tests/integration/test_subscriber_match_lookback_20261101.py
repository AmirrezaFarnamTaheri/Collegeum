"""Offline subscriber browse lookbacks: never change scheduled alert eligibility."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from predoc_pipeline.publish import interactions
from predoc_pipeline.publish.subscriptions import matching
from predoc_pipeline.publish.ui import latest_panel


def _career(age: int) -> dict[str, str]:
    return {
        "key": f"career:age{age}", "category": "data_analyst",
        "scope": "remote", "first_seen_at": (
            datetime.now(UTC) - timedelta(days=age)
        ).isoformat(),
        "title": f"Career age {age}", "employer": "Research Group",
        "location": "Remote", "source": "Jobicy",
        "url": f"https://example.org/jobs/{age}",
    }


@pytest.mark.parametrize(("days", "expected"), [
    (7, {6}), (14, {6, 10}), (30, {6, 10, 25}),
    (60, {6, 10, 25, 50}), (90, {6, 10, 25, 50, 80}),
])
def test_history_window_only_changes_read_only_preview(days: int, expected: set[int]) -> None:
    now = datetime.now(UTC).isoformat()
    member = {"topics": {"data_analyst": now}, "scopes": {"remote": now}}
    jobs = [_career(age) for age in (6, 10, 25, 50, 80, 100)]
    selected = matching(member, [], jobs, preview=True, lookback_days=days)
    assert {int(row["title"].split()[-1]) for row in selected} == expected
    assert matching(member, [], jobs, preview=False, lookback_days=90) == []


def test_latest_keyboard_preserves_90_day_window_across_pages() -> None:
    jobs = [_career(age) for age in (6, 10, 25, 50, 80, 85)]
    _, first = latest_panel(jobs, page=0, lookback_days=90)
    buttons = first["inline_keyboard"]
    choices = [item for row in buttons for item in row]
    assert {f"sub:p:latest:{d}:0" for d in (7, 14, 30, 60, 90)} <= {
        item["callback_data"] for item in choices
    }
    assert any(item["callback_data"] == "sub:p:latest:90:1" for item in choices)
    page2, more = latest_panel(jobs, page=1, lookback_days=90)
    assert "90 days" in page2
    assert any(
        item["callback_data"] == "sub:p:latest:90:0"
        for row in more["inline_keyboard"] for item in row
    )


def test_legacy_callbacks_default_to_14_days_and_invalid_ranges_fail_closed(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []

    def fake_latest(_store, _id, _academic, _settings, page=0, lookback_days=14):
        calls.append((page, lookback_days))
        return "history", {"inline_keyboard": []}

    monkeypatch.setattr(interactions, "_latest", fake_latest)
    def call(raw: str):
        return interactions._page(raw, None, None, 101, None, [])

    for raw, expected in (
        ("sub:p:latest", (0, 14)),
        ("sub:p:latest:1", (1, 14)),
        ("sub:p:latest:7:0", (0, 7)),
        ("sub:p:latest:30:3", (3, 30)),
        ("sub:p:latest:90:1", (1, 90)),
    ):
        assert call(raw) is not None
        assert calls[-1] == expected
    for raw in ("sub:p:latest:999:0", "sub:p:latest:0:0",
                "sub:p:latest:-7:0", "sub:p:latest:90:9999", "sub:p:latestwrong"):
        assert call(raw) is None
