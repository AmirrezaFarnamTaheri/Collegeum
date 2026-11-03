"""Browsing copy must not certify that snapshot listings are still open."""
from __future__ import annotations

from predoc_pipeline.publish.bot import (
    EMPTY,
    HELP,
    OWNER_COMMANDS,
    TITLES,
    build_pages,
)


class FakeStore:
    def status(self, _hash: str) -> None:
        return None

    def marked_at(self, _hash: str) -> None:
        return None

    def with_status(self, _mark: str) -> list:
        return []


def test_legacy_bot_saved_snapshot_cannot_be_named_verified_open_positions():
    owner_positions = dict(OWNER_COMMANDS)["positions"]
    for visible in (owner_positions, HELP, TITLES["positions"], EMPTY["positions"]):
        assert "open position" not in visible.lower()
        assert "open vacanc" not in visible.lower()
    assert "stored" in HELP.lower() or "snapshot" in HELP.lower()
    assert "no matching" in EMPTY["positions"].lower()


def test_rendered_legacy_telegram_page_discloses_availability_uncertainty():
    job = {
        "url_hash": "a" * 64,
        "title": "Research Assistant",
        "institution": "University",
        "city": "London",
        "country": "United Kingdom",
        "deadline": None,
        "deadline_note": None,
        "apply_url": "https://university.example/jobs/1",
        "closed_at": None,
        "expired_at": None,
        "confidence": 0.9,
    }
    rendered = build_pages("positions", [job], FakeStore())
    assert len(rendered) == 1
    text, _ = rendered[0]
    assert "not independently verified" in text.lower()
    assert "open position" not in text.lower()
    assert "Research Assistant" in text
