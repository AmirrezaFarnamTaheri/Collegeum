"""Shared fixtures for the job-board tests (ported from predoc-bot)."""

from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "boards"

TODAY = date(2026, 9, 24)


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    """Pin 'today' so date-relative assertions about the fixtures don't rot."""
    import predoc_pipeline.boards.filter as flt
    import predoc_pipeline.boards.utils.dates as dates

    for mod in (dates, flt):
        monkeypatch.setattr(mod, "today", lambda: TODAY)
    yield TODAY
