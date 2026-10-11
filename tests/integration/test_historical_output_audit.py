"""Deterministic replay tests for the historical-output audit and quarantine."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from tools.audit_pipeline_outputs import inspect, repair


def _write_fixture(root: Path) -> dict[int, dict]:
    (root / "data").mkdir(parents=True)
    (root / "docs/data").mkdir(parents=True)
    rows = [
        {
            "id": index, "url_hash": f"{index:064x}", "status": "published",
            "title": f"Research position {index}", "institution": "University",
            "summary": "Original research position description",
            "apply_url": url, "closed_at": None, "expired_at": None,
            "telegram_message_id": (index + 40) if index % 2 == 0 else None,
            "published_at": "2026-10-09T10:00:00Z",
        }
        for index, url in enumerate([
            "https://www.university.edu/jobs/123",
            "https://www.europeanjobmarketofeconomists.org/role/%5Bnid%5D",
            "https://accounts.google.com/v3/signin/identifier?continue=docs.google.com",
            "http://jobs.hhs.se/en/job/stockholm/real-advert-973026.html",
        ], start=1)
    ]
    rows[2]["summary"] = "Sign in to continue Email or phone Forgot email?"
    (root / "data/listings.ndjson").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8",
    )
    (root / "data/seen.ndjson").write_text("source-history\n", encoding="utf-8")
    (root / "docs/data/listings.json").write_text(
        json.dumps({"generated_at": "2026-10-11T00:00:00Z",
                    "count": len(rows), "listings": rows}), encoding="utf-8",
    )
    (root / "docs/data/health.json").write_text(
        json.dumps({
            "generated_at": "2026-10-11T00:00:00Z", "status": "degraded",
            "last_run": {"run_id": "38139499012", "outcome": "partial"},
            "source_summary": {"failed": 25}, "runs": [],
            "counts": {"listings": 4, "published": 4, "closed": 0, "expired": 0},
        }), encoding="utf-8",
    )
    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<?xml-stylesheet type="text/xsl" href="rss.xsl"?>\n'
        "<rss><channel><title>Collegeum</title>"
    )
    for row in rows:
        rss += (
            f'<item><title>Research {row["id"]}</title>'
            f'<link>{row["apply_url"].replace("&", "&amp;")}</link></item>'
        )
    rss += "</channel></rss>"
    (root / "docs/feed.xml").write_text(rss, encoding="utf-8")
    return {row["id"]: row for row in rows}


def test_historical_repair_is_receipt_preserving_and_idempotent(tmp_path: Path):
    original = _write_fixture(tmp_path)
    before = inspect(tmp_path)
    assert [x["id"] for x in before["journal_quarantine_candidates"]] == [2, 3]
    assert before["invalid_public_ids"] == [2, 3]
    assert len(before["invalid_rss_links"]) == 2
    assert before["pipeline_outcome"] == "partial"

    fixed = repair(
        tmp_path, when=datetime(2026, 10, 11, 17, 0, tzinfo=UTC),
    )
    assert fixed["quarantined_ids"] == [2, 3]
    assert fixed["after"]["public_rows"] == 2
    assert fixed["after"]["rss_items"] == 2
    # Invalid journal links remain auditable after removal from public exports.
    assert [x["id"] for x in fixed["after"]["journal_quarantine_candidates"]] == [2, 3]
    assert fixed["after"]["pipeline_outcome"] == "partial"

    restored = [
        json.loads(line) for line in
        (tmp_path / "data/listings.ndjson").read_text("utf-8").splitlines()
    ]
    assert len(restored) == 4
    assert restored[0] == original[1]
    assert restored[3] == original[4]
    for identifier in (2, 3):
        row = restored[identifier - 1]
        assert row["status"] == "published"
        assert row["telegram_message_id"] == original[identifier]["telegram_message_id"]
        assert row["published_at"] == original[identifier]["published_at"]
        assert row == original[identifier]
        assert row["closed_at"] is None
    assert (tmp_path / "data/seen.ndjson").read_text("utf-8") == "source-history\n"
    assert "xml-stylesheet" in (tmp_path / "docs/feed.xml").read_text("utf-8")
    assert len(ET.parse(tmp_path / "docs/feed.xml").findall("channel/item")) == 2

    health = json.loads((tmp_path / "docs/data/health.json").read_text("utf-8"))
    assert health["status"] == "degraded"
    assert health["last_run"]["run_id"] == "38139499012"
    assert health["counts"]["closed"] == 0
    assert health["output_audit"]["quarantined_ids"] == [2, 3]

    backup = list((tmp_path / "build").glob("output-audit-backup-*"))
    assert len(backup) == 1
    assert len(backup[0].joinpath("docs/data/listings.json").read_text("utf-8")) > 10
    assert inspect(tmp_path)["invalid_public_ids"] == []
    assert repair(tmp_path)["quarantined_ids"] == []
    assert len(list((tmp_path / "build").glob("output-audit-backup-*"))) == 1


def test_corrupt_export_count_aborts_before_mutation(tmp_path: Path):
    _write_fixture(tmp_path)
    dashboard = tmp_path / "docs/data/listings.json"
    payload = json.loads(dashboard.read_text("utf-8"))
    payload["count"] = 99
    dashboard.write_text(json.dumps(payload), encoding="utf-8")
    original = dashboard.read_bytes()
    with pytest.raises(ValueError, match="count"):
        repair(tmp_path)
    assert dashboard.read_bytes() == original
    assert not (tmp_path / "build").exists()


def test_audit_does_not_accuse_specific_http_job_ad_of_being_nonactionable(
    tmp_path: Path,
):
    _write_fixture(tmp_path)
    report = inspect(tmp_path)
    assert all(item["id"] != 4 for item in report["journal_quarantine_candidates"])


def test_output_audit_reports_coded_failures_without_exposing_query_secrets(
    tmp_path: Path,
):
    rows = _write_fixture(tmp_path)
    rss = tmp_path / "docs/feed.xml"
    original = rss.read_text("utf-8")
    url = rows[2]["apply_url"] + "?token=untrusted-secret-value"
    rss.write_text(
        original.replace(rows[2]["apply_url"], url),
        encoding="utf-8",
    )
    report = inspect(tmp_path)
    assert report["invalid_rss_links"]
    assert all(value in (
        "unresolved-url-template", "authentication-redirect",
        "invalid-url", "generic-job-board-homepage",
    ) for value in report["invalid_rss_links"])
    assert "untrusted-secret-value" not in json.dumps(report)


def test_confirmed_source_facts_survive_public_rebuild(tmp_path: Path):
    """Durable source-reviewed corrections cannot regress on subsequent runs."""
    from predoc_pipeline.core.output_quality import excluded_by_audit

    root = Path(__file__).resolve().parents[2]
    rows = {
        entry["id"]: entry
        for line in (root / "data/listings.ndjson").read_text("utf-8").splitlines()
        if (entry := json.loads(line)) and entry["id"] in {28, 46, 77, 139, 173}
    }
    assert rows[46]["institution"].startswith("University of Pennsylvania")
    assert "upenn.wd1.myworkdayjobs.com" in rows[46]["apply_url"]
    assert rows[46]["salary_currency"] == "USD"
    assert rows[77]["salary_currency"] == "CAD"
    assert rows[77]["salary_min"] == 114952.5
    assert rows[77]["salary_max"] == 156778
    assert rows[139]["min_degree"] == "masters"
    assert rows[139]["tools_required"] == "[]"
    assert "jobs.unisg.ch" in rows[139]["apply_url"]
    assert "Institute for Financial Management" in rows[173]["institution"]
    assert "jobs.unibe.ch" in rows[173]["apply_url"]
    assert rows[173]["min_degree"] == "unstated"
    assert excluded_by_audit(rows[28]["url_hash"])
    assert not excluded_by_audit(rows[77]["url_hash"])
    public = json.loads((root / "docs/data/listings.json").read_text("utf-8"))
    entries = {item["id"]: item for item in public["listings"]}
    assert 28 not in entries
    assert entries[46]["institution"] == rows[46]["institution"]
    assert entries[77]["kind"] == "research"
    assert entries[77]["salary_min"] == rows[77]["salary_min"]
    assert entries[139]["min_degree"] == "masters"
    assert entries[173]["institution"] == rows[173]["institution"]
