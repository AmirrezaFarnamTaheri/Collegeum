"""Regressions for source coverage and evidence-preserving Life Sciences exports."""
from __future__ import annotations

import asyncio
import csv
import json

from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.ingest import life_sciences
from tools import export_life_sciences


def test_rotation_prioritizes_source_missing_a_health_observation(tmp_path):
    config = tmp_path / "life_sciences.toml"
    config.write_text(
        "".join(
            f'[[board]]\nname="life_source_{index:02d}"\n'
            'type="link_scan"\nurl="https://example.org/jobs"\n'
            for index in range(13)
        ),
        encoding="utf-8",
    )
    rotation = tmp_path / "rotation.json"
    rotation.write_text(
        json.dumps({
            "attempts": {
                **{
                    f"life_source_{index:02d}": "2026-10-28T00:00:00+00:00"
                    for index in range(12)
                },
                "life_source_12": "2026-10-30T23:00:00+00:00",
            },
            "last_slot": 0,
        }),
        encoding="utf-8",
    )
    health = tmp_path / "health.json"
    health.write_text(
        json.dumps({
            "sources": {
                **{
                    f"life_source_{index:02d}": {
                        "status": "discovered",
                        "last_checked_at": "2026-10-30T12:00:00+00:00",
                    }
                    for index in range(12)
                },
                "life_source_12": {"status": "never_checked"},
            },
        }),
        encoding="utf-8",
    )
    selected = life_sciences.select_sources(config, rotation, health_path=health)
    assert len(selected) == life_sciences.MAX_SOURCES
    assert "life_source_12" in selected


def test_newly_observed_deadline_wins_csv_dedup_without_erasing_first_seen(tmp_path):
    original = {
        "title": "PhD Position in Epigenetics",
        "url": "https://example.org/jobs/123",
        "employer": "Example Institute",
        "country": "Netherlands",
        "deadline": "2026-11-02",
        "funding_status": "unverified",
        "first_seen_at": "2026-10-20T00:00:00+00:00",
        "last_seen_at": "2026-10-20T00:00:00+00:00",
        "availability": "unknown",
    }
    fresh = {
        **original,
        "deadline": "2026-11-30",
        "first_seen_at": "2026-10-31T00:00:00+00:00",
        "last_seen_at": "2026-10-31T00:00:00+00:00",
    }
    output = tmp_path / "export.csv"
    assert export_life_sciences.write_csv(output, [original, fresh]) == 1
    with output.open(encoding="utf-8-sig", newline="") as stream:
        record = next(csv.DictReader(stream))
    assert record["deadline"] == "2026-11-30"
    assert record["first_seen_at"] == original["first_seen_at"]
    assert record["last_seen_at"] == fresh["last_seen_at"]


def test_live_export_retains_job_specific_country_over_board_hint(tmp_path, monkeypatch):
    config = tmp_path / "life_sciences.toml"
    config.write_text(
        '[[board]]\nname="life_test"\ntype="link_scan"\n'
        'url="https://example.org/jobs"\n',
        encoding="utf-8",
    )
    vacancy = JobPostSchema(
        title="PhD Position in Epigenetics",
        url="https://example.org/jobs/987",
        source="life_test",
        country="Netherlands",
        location="Stockholm, Sweden",
        institution="Example Institute",
        fields_of_research="Epigenetics",
        extra={"source_country_default": True},
    )

    async def fake_discover(*_args, **_kwargs):
        return [vacancy], []

    monkeypatch.setattr(life_sciences, "discover", fake_discover)
    output = tmp_path / "export.csv"
    report = {"collected_at": "2026-10-31T08:00:00+00:00", "batches": []}
    asyncio.run(export_life_sciences.collect(config, [], output, report))
    with output.open(encoding="utf-8-sig", newline="") as stream:
        record = next(csv.DictReader(stream))
    assert record["country"] == "Sweden"
    assert record["location"] == "Stockholm, Sweden"
