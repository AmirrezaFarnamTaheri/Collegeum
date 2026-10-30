"""Life Sciences CSV must be interpretable without implying verification."""
from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from tools.export_life_sciences import artifact_quality, write_csv


def test_life_sciences_csv_marks_unverified_availability_explicitly(tmp_path: Path):
    rows = [{
        "key": "career:aa", "category": "life_sciences_phd", "scope": "",
        "title": "PhD in Gene Regulation", "employer": "University of Basel",
        "location": "Switzerland", "url": "https://unibas.ch/jobs/100",
        "source": "life_basel", "funding_status": "unverified",
        "first_seen_at": "2026-10-20T00:00:00+00:00",
        "last_seen_at": "2026-10-20T00:00:00+00:00",
    }]
    path = tmp_path / "life.csv"
    assert write_csv(path, rows) == 1
    with path.open(encoding="utf-8-sig", newline="") as handle:
        record = next(csv.DictReader(handle))
    assert record["country"] == "Switzerland"
    assert record["availability"] == "unknown"
    assert record["funding_status"] == "unverified"
    assert record["application_url"] == "https://unibas.ch/jobs/100"


def test_export_quality_distinguishes_staleness_and_field_completeness():
    rows = [
        {
            "title": "PhD in Chromatin", "country": "", "location": "Belgium",
            "source": "life_vib", "employer": "VIB",
            "url": "https://jobs.vib.be/j/100/a", "availability": "unknown",
            "funding_status": "unverified",
            "last_seen_at": "2026-10-20T00:00:00+00:00",
        },
        {
            "title": "PhD in RNA Biology", "country": "Sweden", "location": "Sweden",
            "source": "life_karolinska", "employer": "KI",
            "url": "https://ki.varbi.com/jobs/200", "availability": "active",
            "funding_status": "unverified",
            "last_seen_at": "2026-10-29T10:00:00+00:00",
        },
        {
            "title": "PhD in Epigenetics", "country": "", "location": "Unspecified",
            "source": "life_euraxess", "employer": "Institute",
            "url": "https://euraxess.ec.europa.eu/jobs/300",
            "last_seen_at": "2026-10-29T10:00:00+00:00",
        },
    ]
    report = artifact_quality(rows, now=datetime(2026, 10, 30, tzinfo=UTC))
    assert report["rows"] == 3
    assert report["unique_urls"] == 3
    assert report["country"]["explicit"] == 1
    assert report["country"]["derived_from_location"] == 1
    assert report["country"]["unknown"] == 1
    assert report["availability"]["unknown"] == 2
    assert report["funding_unverified"] == 3
    assert report["last_seen_older_than_7d"] == 1
    assert report["verified_open_count"] == 0
    assert report["limits"]["no_current_application_verification"]


def test_export_quality_detects_cross_source_same_url_without_deleting_rows():
    jobs = [
        {"url": "https://euraxess.ec.europa.eu/jobs/22", "source": "life_euraxess"},
        {"url": "https://euraxess.ec.europa.eu/jobs/22", "source": "life_euraxess_rna"},
    ]
    report = artifact_quality(jobs, now=datetime(2026, 10, 30, tzinfo=UTC))
    assert report["rows"] == 2
    assert report["unique_urls"] == 1
    assert report["duplicate_url_rows"] == 1
