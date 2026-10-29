"""Employer-verified HBS 2027 predoctoral qualification and public routing.

Official evidence (reviewed 2026-10-29):
Harvard Careers requisition JID-2162 (bachelor's degree and GPA above 3.5 required).
https://www.hbs.edu/ra/apply

The original extraction incorrectly asserted that a completed PhD was required,
which made an actual predoctoral position appear under doctorate-qualified research.
"""

import json
from pathlib import Path

from predoc_pipeline import state
from predoc_pipeline.boards.config import load_preferences
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.routing import Router

ROOT = Path(__file__).resolve().parents[2]
HBS_ID = 88


def _journal_hbs():
    return next(
        record for line in (ROOT / "data/listings.ndjson").read_text("utf-8").splitlines()
        if (record := json.loads(line))["id"] == HBS_ID
    )


def _dashboard_hbs(path=ROOT / "docs/data/listings.json"):
    items = json.loads(path.read_text("utf-8"))["listings"]
    return next(row for row in items if row["id"] == HBS_ID)


def test_official_hbs_bachelors_qualification_not_completed_phd():
    row = _journal_hbs()
    assert row["title"] == "Predoctoral Research Associate"
    assert row["institution"] == "Harvard Business School"
    assert row["apply_url"].endswith("jid-2162")
    assert row["min_degree"] == "bachelors"
    assert "graduate degree not required" in row["degree_note"].lower()
    assert Router.position_kind(
        row["title"], row["summary"], min_degree=row["min_degree"],
        degree_note=row["degree_note"],
    ) == "predoc"


def test_hbs_corrected_degree_and_kind_in_public_dashboard():
    published = _dashboard_hbs()
    assert published["kind"] == "predoc"
    assert published["min_degree"] == "bachelors"
    assert published["degree_note"] == _journal_hbs()["degree_note"]


def test_hbs_corrected_facts_survive_db_restore_and_dashboard_regeneration(tmp_path):
    source = _journal_hbs()
    db_path = tmp_path / "predoc.db"
    output = tmp_path / "listings.json"
    init(db_path)
    with Database(db_path) as db:
        state.restore_if_needed(
            db, ROOT / "data/listings.ndjson", ROOT / "data/seen.ndjson"
        )
        state.export_dashboard(
            db, output,
            router=Router(load_preferences(ROOT / "config/preferences.toml")),
        )
    actual = _dashboard_hbs(output)
    assert actual["min_degree"] == "bachelors"
    assert actual["kind"] == "predoc"
    assert actual["source_url"] == source["source_url"]
    assert actual["apply_url"] == source["apply_url"]
