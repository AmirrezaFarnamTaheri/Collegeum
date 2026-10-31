"""Historical Bern API index end dates are not employer application deadlines.

The original journal remains immutable. Only the generated CSV presentation
may remove reviewed false cutoff claims; known employer-confirmed hard dates
must remain available.
"""
from __future__ import annotations

import csv
import json

from tests.boards.test_bern_employer_advert_verification_20261031 import (
    BIOENERGY,
    CANCER,
    GENESIS_WET,
    TRANSLATIONAL,
)
from tools.export_life_sciences import stored_positions, write_csv


def test_historical_bern_false_deadlines_are_redacted_in_csv_without_journal_changes(
    tmp_path,
) -> None:
    observations = [
        (CANCER, "Cancer Immunology", "2026-11-27", "unverified"),
        (GENESIS_WET, "NCCR Genesis: life detection", "2026-12-31", "rolling"),
        (BIOENERGY, "Bottom-up Bioenergetics", "2026-11-20", "confirmed"),
        (TRANSLATIONAL, "Translational Cancer Research", "2026-11-15", "confirmed"),
    ]
    history = [
        {
            "key": f"career:bern-audit-{i}",
            "category": "life_sciences_phd", "scope": "",
            "source": "life_dach_bern", "url": url,
            "title": title, "employer": "University of Bern",
            "deadline": deadline,
            "deadline_note": f"Official UniBE posting ends {deadline}T22:59:59Z",
            "funding_status": "unverified",
        }
        for i, (url, title, deadline, _expected) in enumerate(observations)
    ]
    journal = tmp_path / "career_jobs.ndjson"
    payload = "".join(json.dumps(x) + "\n" for x in history)
    journal.write_text(payload, encoding="utf-8")
    csv_path = tmp_path / "life.csv"

    assert write_csv(csv_path, stored_positions(journal)) == 4
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        exported = {row["application_url"]: row for row in csv.DictReader(handle)}
    assert exported[CANCER]["deadline"] == ""
    assert "unverified" in exported[CANCER]["deadline_note"].casefold()
    assert exported[GENESIS_WET]["deadline"] == ""
    assert "rolling" in exported[GENESIS_WET]["deadline_note"].casefold()
    assert exported[BIOENERGY]["deadline"] == "2026-11-20"
    assert exported[TRANSLATIONAL]["deadline"] == "2026-11-15"
    assert journal.read_text(encoding="utf-8") == payload
