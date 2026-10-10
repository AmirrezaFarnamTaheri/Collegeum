"""Ambiguous HTTP 404 results require independent dated confirmation."""

from datetime import UTC, datetime, timedelta

from predoc_pipeline.core import db as db_module
from predoc_pipeline.core.db import Database, init


def test_404_not_terminal_until_two_independent_days(tmp_path, monkeypatch):
    path = tmp_path / "listings.sqlite3"
    init(path)
    start = datetime(2026, 10, 10, tzinfo=UTC)
    current = [start]
    monkeypatch.setattr(db_module, "now", lambda: current[0].strftime("%Y-%m-%dT%H:%M:%SZ"))
    with Database(path) as db:
        lid = db.insert_listing({
            "url_hash": "abc", "apply_url": "https://example.org/job",
            "source_url": "https://example.org/job", "source": "test",
            "title": "Research assistant", "institution": "Example",
        })
        assert not db.observe_http_404(lid)
        assert not db.observe_http_404(lid)  # same run/day is not independent
        assert db.listing(lid)["missing_404_observations"] == 1
        current[0] = start + timedelta(hours=23)
        assert not db.observe_http_404(lid)
        current[0] = start + timedelta(hours=25)
        assert db.observe_http_404(lid)
        assert db.listing(lid)["missing_404_observations"] == 2


def test_successful_recheck_resets_404_streak(tmp_path):
    path = tmp_path / "listings.sqlite3"
    init(path)
    with Database(path) as db:
        lid = db.insert_listing({
            "url_hash": "xyz", "apply_url": "https://example.org/other",
            "source_url": "https://example.org/other", "source": "test",
            "title": "Research assistant", "institution": "Example",
        })
        assert not db.observe_http_404(lid)
        db.clear_http_404(lid)
        assert db.listing(lid)["missing_404_observations"] == 0
        assert db.listing(lid)["missing_404_at"] is None
        assert not db.observe_http_404(lid)
