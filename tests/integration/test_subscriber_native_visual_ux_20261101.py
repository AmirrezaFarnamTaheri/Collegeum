"""Polling-bot UI keeps the same compact layout and navigation as Cloudflare."""
from __future__ import annotations

from predoc_pipeline.publish.ui import menu


def _member(language: str) -> dict:
    return {
        "topics": {
            "predoc": "2026-10-01T00:00:00+00:00",
            "phd": "2026-10-01T00:00:00+00:00",
            "data_analyst": "2026-10-01T00:00:00+00:00",
        },
        "scopes": {"remote": "2026-10-01T00:00:00+00:00"},
        "academic_regions": {"europe": "2026-10-02T00:00:00+00:00"},
        "paused": False,
        "language": language,
    }


def _actions(keyboard: dict) -> list[str]:
    return [b["callback_data"] for row in keyboard["inline_keyboard"] for b in row]


def test_polling_home_prioritizes_browse_and_separates_search_from_alerts() -> None:
    for language in ("en", "fa"):
        text, keyboard = menu(_member(language))
        assert "<b>Collegeum</b>" in text or "<b>کالجیوم</b>" in text
        assert "🎓" in text and "💼" in text
        assert keyboard["inline_keyboard"][0][0]["callback_data"] == "sub:p:latest"
        assert "sub:p:subscriptions" in _actions(keyboard)
        assert "sub:p:delivery" in _actions(keyboard)
        assert len(keyboard["inline_keyboard"]) <= 6


def test_polling_academic_and_careers_have_compact_grids_and_explicit_steps() -> None:
    for language in ("en", "fa"):
        for page in ("academic", "careers"):
            text, keyboard = menu(_member(language), page)
            role_rows = [row for row in keyboard["inline_keyboard"] if
                         any(b["callback_data"].startswith("sub:t:") for b in row)]
            assert [len(row) for row in role_rows] == [2, 2]
            assert all(len(b["text"]) <= 29 for row in role_rows for b in row)
            assert ("Step 1" if language == "en" else "مرحله ۱") in text
            assert "sub:p:subscriptions" in _actions(keyboard)
            assert len(text) < 900


def test_polling_subscription_summary_and_regions_preserve_legacy_routes() -> None:
    for language in ("en", "fa"):
        text, keyboard = menu(_member(language), "subscriptions")
        assert "🧭" in text and "🎓" in text and "💼" in text
        assert "sub:p:markets" not in _actions(keyboard)
        regions, regional_keyboard = menu(_member(language), "academic_regions")
        assert "sub:r:all" in _actions(regional_keyboard)
        assert "Europe" in regions or "اروپا" in regions
        assert len(regions) <= 700
        assert all(len(row) <= 2 for row in regional_keyboard["inline_keyboard"])
