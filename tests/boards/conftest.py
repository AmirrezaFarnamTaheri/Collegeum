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


@pytest.fixture(autouse=True)
def clean_llm_env(monkeypatch):
    """Ensure host environment keys do not leak into board pipeline tests."""
    for var in (
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "NVIDIA_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "MISTRAL_API_KEY",
        "MEMO_API_KEY",
        "CUSTOM_LLM_API_KEY",
        "EXTRACTION_BACKEND",
    ):
        monkeypatch.delenv(var, raising=False)
