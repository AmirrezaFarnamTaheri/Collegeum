"""Retain Life Sciences vacancy metadata through the private career journal.

A real source often has a deadline/department/field, but the scheduled
collector previously dropped that evidence; the CSV then showed blank
application deadlines even though detail discovery had seen them.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from predoc_pipeline.boards.config import HttpConfig
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.ingest import life_sciences
from predoc_pipeline.ingest.career import load_career
from tools.export_life_sciences import write_csv


def _posting():
    return JobPostSchema(
        source="life_karolinska", title="PhD student in Epigenetics",
        url="https://ki.varbi.com/en/job/999999/phd-student-epigenetics",
        institution="Karolinska Institutet", country="Sweden",
        location="Stockholm, Sweden", department="Medical Genomics",
        fields_of_research="Epigenetics, chromatin and gene regulation",
        description_snippet="Required: Master's degree in molecular biology.",
        date_posted=date(2026, 10, 15),
        deadline=date(2026, 12, 15),
        deadline_text="Applications close 15 December 2026",
    )


def test_scheduled_life_classification_keeps_verified_source_metadata():
    result = life_sciences.classify_post(_posting(), today=date(2026, 10, 30))
    assert result is not None
    assert result["research_fields"] == "Epigenetics, chromatin and gene regulation"
    assert result["deadline"] == "2026-12-15"
    assert result["deadline_note"] == "Applications close 15 December 2026"
    assert result["date_posted"] == "2026-10-15"
    assert result["availability"] == "unknown"
    assert result["funding_status"] == "unverified"


def test_life_scheduled_collector_persists_source_deadline_without_alert_replay(
    tmp_path: Path, monkeypatch,
):
    config = tmp_path / "life_sciences.toml"
    config.write_text(
        '[[board]]\nname="life_karolinska"\ntype="link_scan"\n'
        'url="https://example.org/jobs"\nlink_pattern="example.org/job"\n',
        encoding="utf-8",
    )
    journal = tmp_path / "career.ndjson"
    outputs = tmp_path / "phd.csv"

    async def discover_fake(_src, _http, *, selected_names):
        assert selected_names == {"life_karolinska"}
        return [_posting()], []

    monkeypatch.setattr(life_sciences, "discover", discover_fake)
    first, errors = life_sciences.poll_life_sciences(
        journal, sources_path=config, http_config=HttpConfig(),
    )
    assert (first, errors) == (1, [])
    jobs = load_career(journal)
    assert len(jobs) == 1
    assert jobs[0]["deadline"] == "2026-12-15"
    assert jobs[0]["research_fields"] == "Epigenetics, chromatin and gene regulation"
    assert jobs[0]["availability"] == "unknown"

    assert write_csv(outputs, jobs) == 1
    contents = outputs.read_text(encoding="utf-8-sig")
    assert "2026-12-15" in contents
    assert "Epigenetics, chromatin and gene regulation" in contents
    assert "unknown" in contents

    original_first_seen = jobs[0]["first_seen_at"]
    count, errors = life_sciences.poll_life_sciences(
        journal, sources_path=config, http_config=HttpConfig(),
    )
    assert (count, errors) == (0, [])
    assert load_career(journal)[0]["first_seen_at"] == original_first_seen


def test_original_legacy_journal_is_not_edited_during_new_export(tmp_path: Path):
    original = [{
        "category": "life_sciences_phd", "key": "career:historic-42",
        "title": "PhD in RNA Biology", "source": "life_karolinska",
        "url": "https://ki.varbi.com/en/job/42", "employer": "Karolinska",
        "location": "Sweden", "first_seen_at": "2026-10-01T00:00:00Z",
        "funding_status": "unverified",
    }]
    journal = tmp_path / "career.ndjson"
    journal.write_text(
        json.dumps(original[0], ensure_ascii=False) + "\n", encoding="utf-8",
    )
    before = journal.read_bytes()
    write_csv(tmp_path / "historical.csv", original)
    assert journal.read_bytes() == before
