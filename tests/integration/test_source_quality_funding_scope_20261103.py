"""Funding status is applicable to doctoral career positions, not general analysts."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tools.audit_source_quality import audit

CHECKED_AT = "2026-11-03T12:00:00Z"


def fixture_root(root: Path, rows: list[dict[str, str]]) -> Path:
    def save(path: str, data: object):
        full = root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(json.dumps(data), encoding="utf-8")

    source_counts = {
        "total": 1, "successful": 1, "empty": 0,
        "failed": 0, "partial": 0, "skipped": 0,
    }
    save("docs/data/health.json", {
        "generated_at": CHECKED_AT,
        "last_run": {"run_id": "test-run", "sources": source_counts, "outcome": "ok"},
        "source_summary": source_counts,
    })
    save("data/career_health.json", {"sources": {}})
    save("data/life_sources_health.json", {
        "checked_at": CHECKED_AT,
        "sources": {},
        "summary_this_run": {
            "discovered": 0, "failed": 0, "partial": 0, "skipped": 0,
            "unsupported": 0, "unverified_empty": 0, "verified_empty": 0,
        },
        "checked_this_run": 0,
        "catalogue": {"total": 0, "enabled": 0, "disabled": 0},
    })
    save("docs/data/listings.json", {"listings": []})
    career = root / "data/career_jobs.ndjson"
    career.write_text(
        "".join(json.dumps({
            "key": str(i), "url": f"https://example.org/jobs/{i}",
            "first_seen_at": CHECKED_AT, **row,
        }) + "\n" for i, row in enumerate(rows)),
        encoding="utf-8",
    )
    return root


def test_funding_unverified_counts_only_doctoral_applicable_records(tmp_path: Path):
    root = fixture_root(tmp_path, [
        {"category": "life_sciences_phd", "funding_status": "unverified"},
        {"category": "life_sciences_phd", "funding_status": "verified"},
        {"category": "data_analyst", "funding_status": "unknown"},
    ])
    result = audit(root, now=datetime(2026, 11, 3, 12, 0, tzinfo=UTC))
    assert result["career"]["rows"] == 3
    assert result["career"]["funding_applicable_rows"] == 2
    assert result["career"]["funding_unverified"] == 1
    assert "career:funding-unverified" in result["operational_observations"]
    assert not result["integrity_findings"]


def test_analyst_only_career_does_not_emit_false_funding_degradation(tmp_path: Path):
    root = fixture_root(tmp_path, [
        {"category": "data_analyst", "funding_status": "unknown"},
        {"category": "data_analyst"},
    ])
    result = audit(root, now=datetime(2026, 11, 3, 12, 0, tzinfo=UTC))
    assert result["career"]["funding_applicable_rows"] == 0
    assert result["career"]["funding_unverified"] == 0
    assert "career:funding-unverified" not in result["operational_observations"]
