"""PR #30 merge-gate regressions: logging, durable facts and eval reporting."""

from __future__ import annotations

import json
import logging
import sys
from types import SimpleNamespace

import structlog
from typer.testing import CliRunner

from predoc_pipeline import logging_setup
from predoc_pipeline.core.db import Database, init


def test_console_renderer_preserves_stdlib_exception_tracebacks(monkeypatch):
    """The terminal renderer must show the exception, not fall back to JSON."""
    monkeypatch.setattr(
        logging_setup, "_RENDERER", structlog.dev.ConsoleRenderer(colors=False)
    )
    try:
        raise ValueError("traceback-kept")
    except ValueError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        name="predoc_pipeline.test", level=logging.ERROR, pathname=__file__,
        lineno=1, msg="failed", args=(), exc_info=exc_info,
    )
    rendered = logging_setup.render_record(record)
    assert not rendered.lstrip().startswith("{"), rendered
    assert "ValueError" in rendered
    assert "traceback-kept" in rendered


def test_corrected_journal_clears_stale_cached_salary(tmp_path):
    """A corrected journal must win over an older local SQLite observation."""
    from predoc_pipeline.state import read_journal

    record = next(
        row for row in read_journal("data/listings.ndjson") if row.get("id") == 148
    )
    assert record["salary_min"] is None and record["salary_max"] is None
    old = dict(record)
    old["last_seen_at"] = "2026-10-11T21:50:31Z"
    old["salary_min"] = 2026.0
    old["salary_max"] = 2026.0
    path = tmp_path / "restored.db"
    init(path)
    with Database(path) as db:
        assert db.import_rows([old]) == 1
        assert db.import_rows([record]) == 0
        recovered = db.listing_by_url_hash(record["url_hash"])
        assert recovered is not None
        assert recovered["salary_min"] is None, recovered["salary_min"]
        assert recovered["salary_max"] is None, recovered["salary_max"]


def test_clearing_one_false_salary_bound_retains_valid_other_bound_metadata():
    """Do not erase currency/period when a good second salary bound survives."""
    from predoc_pipeline.pipeline import _clear_stale_salary

    class DatabaseSpy:
        cleared: list[str] = []

        def clear_listing_facts(self, listing_id: int, columns: list[str]) -> None:
            assert listing_id == 148
            self.cleared.extend(columns)

    db = DatabaseSpy()
    stored = {
        "salary_min": 2026.0,
        "salary_max": 3000.0,
        "salary_raw": "2026 rates; GBP 3000 per month",
        "salary_currency": "GBP",
        "salary_period": "month",
    }
    new = SimpleNamespace(
        salary_min=None, salary_max=None, salary_raw=stored["salary_raw"]
    )
    _clear_stale_salary(db, 148, stored, new, {})
    assert db.cleared == ["salary_min"], db.cleared


def test_eval_reports_metrics_for_each_gate_path(tmp_path):
    """A blended precision/recall estimate must not masquerade as a board score."""
    from predoc_pipeline.cli import app

    fixtures = tmp_path / "mixed.jsonl"
    fixtures.write_text(
        "\n".join(json.dumps(row) for row in [
            {
                "text": "Economics department hiring a full-time research assistant.",
                "title": "Research Assistant",
                "expect_pass": True,
            },
            {
                "text": "PhD positions | Postdocs | Jobs",
                "title": "Research Assistant",
                "known_vacancy": True,
                "expect_pass": True,
            },
        ]) + "\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["eval", "--fixtures", str(fixtures)])
    assert result.exit_code == 0, result.output
    assert "strict: n=1" in result.output, result.output
    assert "board: n=1" in result.output, result.output
    assert "precision=" in result.output and "recall=" in result.output
