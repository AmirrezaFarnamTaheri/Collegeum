"""Life Sciences CSV retains verified workplace country for historical journal rows."""
import csv

from tools.export_life_sciences import write_csv


def test_legacy_life_sciences_journal_country_is_exported_from_known_location(tmp_path):
    output = tmp_path / "life.csv"
    rows = [
        {
            "category": "life_sciences_phd",
            "title": "PhD position in Molecular Biology",
            "employer": "Umea University",
            "location": "Sweden",
            "url": "https://example.org/jobs/doctoral-1",
            "funding_status": "unverified",
        },
        {
            "category": "life_sciences_phd",
            "title": "PhD position in Chromatin",
            "employer": "Utrecht University",
            "location": "Utrecht",
            "country": "Netherlands",
            "url": "https://example.org/jobs/doctoral-2",
            "funding_status": "unverified",
        },
    ]
    assert write_csv(output, rows) == 2
    with output.open(encoding="utf-8-sig", newline="") as fh:
        exported = list(csv.DictReader(fh))
    by_url = {row["application_url"]: row for row in exported}
    assert by_url["https://example.org/jobs/doctoral-1"]["country"] == "Sweden"
    assert by_url["https://example.org/jobs/doctoral-2"]["country"] == "Netherlands"
    assert all(row["funding_status"] == "unverified" for row in exported)


def test_unresolved_location_does_not_invent_workplace_country(tmp_path):
    output = tmp_path / "life.csv"
    write_csv(output, [{
        "title": "PhD position in Chromatin",
        "location": "Online anywhere",
        "url": "https://example.org/jobs/doctoral-3",
    }])
    with output.open(encoding="utf-8-sig", newline="") as fh:
        row = next(csv.DictReader(fh))
    assert row["country"] == ""
