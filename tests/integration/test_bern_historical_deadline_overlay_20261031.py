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



def test_private_selection_masks_same_stale_dates_without_mutating_receipts() -> None:
    """A generated CSV must not be safer than the private/preview data view."""
    from copy import deepcopy
    from datetime import UTC, datetime

    from predoc_pipeline.publish.subscriptions import matching

    now = datetime.now(UTC).isoformat()
    history = [
        {
            "key": f"career:immutable-{number}", "category": "life_sciences_phd",
            "scope": "", "source": "life_dach_bern", "url": url,
            "title": title, "employer": "University of Bern",
            "first_seen_at": now, "availability": "unknown",
            "deadline": deadline,
            "deadline_note": f"Official UniBE posting ends {deadline}T22:59:59Z",
        }
        for number, (url, title, deadline) in enumerate((
            (CANCER, "PhD Student in Cancer Immunology", "2026-11-27"),
            (GENESIS_WET, "PhD NCCR Genesis: combined life detection", "2026-12-31"),
            (BIOENERGY, "PhD position in Bottom-up Bioenergetics", "2026-11-20"),
            (TRANSLATIONAL, "PhD Student in Translational Cancer Research", "2026-11-15"),
        ))
    ]
    originals = deepcopy(history)
    member = {
        "topics": {"life_sciences_phd": "2026-10-01T00:00:00Z"},
        "scopes": {},
    }
    chosen = {row["url"]: row for row in matching(member, [], history, preview=True)}
    assert len(chosen) == 4
    assert chosen[CANCER]["deadline"] == ""
    assert "unverified" in chosen[CANCER]["deadline_note"].lower()
    assert chosen[GENESIS_WET]["deadline"] == ""
    assert "rolling" in chosen[GENESIS_WET]["deadline_note"].lower()
    assert chosen[BIOENERGY]["deadline"] == "2026-11-20"
    assert chosen[TRANSLATIONAL]["deadline"] == "2026-11-15"
    assert history == originals
    assert chosen[CANCER]["key"] == originals[0]["key"]
    assert chosen[CANCER]["first_seen_at"] == originals[0]["first_seen_at"]


def test_exact_verified_uuid_matches_official_locale_variants_only(tmp_path) -> None:
    """A changed slug or Swiss-language path must not evade employer review."""
    from predoc_pipeline.ingest.life_sciences import historical_life_title_disqualified

    # Same immutable viewkey in Bern's approved German-language URL path.
    translated = (
        "https://jobs.unibe.ch/offene-stellen/neuer-stellentitel/"
        "a5825edd-e430-405e-a30e-935d10b872db"
    )
    assert historical_life_title_disqualified("PhD in microbial detection", translated)
    assert not historical_life_title_disqualified(
        "PhD in microbial detection",
        "https://jobs.unibe.ch.evil.example/offene-stellen/neuer-stellentitel/"
        "a5825edd-e430-405e-a30e-935d10b872db",
    )
    # Retain the same journal identity; only the exported view is redacted.
    journal = tmp_path / "journal.ndjson"
    record = {
        "key": "career:immutable-reviewed-job",
        "category": "life_sciences_phd", "scope": "",
        "source": "life_dach_bern", "title": "PhD cancer immunology",
        "url": (
            "https://jobs.unibe.ch/offene-stellen/lokalisierte-stelle/"
            "0a6853ac-d531-4ac1-bc57-592090585e19"
        ),
        "deadline": "2026-11-27",
        "deadline_note": "Official UniBE posting ends 2026-11-27T22:59:59Z",
    }
    original = json.dumps(record) + "\n"
    journal.write_text(original, encoding="utf-8")
    csv_path = tmp_path / "export.csv"
    assert write_csv(csv_path, stored_positions(journal)) == 1
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        row = next(iter(csv.DictReader(handle)))
    assert row["deadline"] == ""
    assert journal.read_text(encoding="utf-8") == original
