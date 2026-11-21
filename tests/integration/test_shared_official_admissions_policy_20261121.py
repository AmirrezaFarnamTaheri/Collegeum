"""Admissions publisher and recovery watchdog must enforce the same source proof."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from predoc_pipeline.publish.admissions import eligible_official_admissions
from tools.ingestion_watchdog import evaluate_admissions_trigger

NOW = datetime(2026, 11, 21, 15, tzinfo=UTC)
BSE = "https://bse.eu/masters-degrees/economics-finance/upf-phd-track"
BERLIN = "https://berlinschoolofeconomics.de/phd-program/application"
RUNS = [{
    "name": "predoc-pipeline", "head_branch": "main",
    "status": "completed", "created_at": "2026-11-21T12:00:00Z",
}]
LEDGER = {"version": 1, "deliveries": {}}


def row():
    return {
        "institution": "Berlin School of Economics", "country_code": "DE",
        "official_programme_url": BERLIN, "evidence_url": BERLIN,
        "status": "verified", "checked_at": "2026-11-21T14:00:00Z",
        "deadline_iso": "2027-01-15",
        "evidence_excerpt": "Economics PhD application deadline: January 15, 2027",
    }


def catalog(*rows):
    return {
        "kind": "economics_phd_admissions_observations",
        "scope": "official_programme_sources_only",
        "source": {"deadline_values_reused": False},
        "programmes": list(rows),
    }


def dispatch(*rows):
    return evaluate_admissions_trigger(
        catalog(*rows), LEDGER, RUNS, now=NOW,
    ).dispatch


def test_wrong_country_claim_on_generic_host_is_never_a_recovery_trigger():
    invalid = row()
    invalid.update(
        institution="Barcelona School of Economics", country_code="ES",
        official_programme_url=BSE, evidence_url=BSE,
        investigated_urls=[BSE, "https://bse.eu/contact"],
        official_details={"institution_country": {
            "value": "Germany", "evidence_url": "https://bse.eu/contact",
            "checked_at": invalid["checked_at"],
            "evidence_excerpt": "Mailing address: Berlin, Germany",
        }},
    )
    assert eligible_official_admissions(catalog(invalid), now=NOW) == []
    assert not dispatch(invalid)


def test_legitimate_query_url_and_separate_admissions_evidence_path_still_work():
    eui = {
        **row(), "institution": "European University Institute",
        "country_code": "IT",
        "official_programme_url": "https://www.eui.eu/apply?id=doctoral-programme-in-economics",
        "evidence_url": "https://www.eui.eu/apply?id=doctoral-programme-in-economics",
        "evidence_excerpt": "The deadline to apply for 2027-28 is 15 January 2027.",
    }
    assert eligible_official_admissions(catalog(eui), now=NOW) == [eui]
    assert dispatch(eui)


def test_opening_and_closing_dates_can_coexist_when_funding_deadline_is_exact():
    aalto = {
        **row(), "institution": "Aalto University", "country_code": "FI",
        "official_programme_url": "https://www.aalto.fi/en/study-options/doctoral-programme",
        "evidence_url": "https://www.aalto.fi/en/study-options/doctoral-programme",
        "deadline_iso": "2027-01-05",
        "evidence_excerpt": (
            "Admission schedule 2027: Application period opens on 8 December 2026 "
            "and closes on 5 January 2027."
        ),
    }
    assert eligible_official_admissions(catalog(aalto), now=NOW) == [aalto]
    assert dispatch(aalto)


@pytest.mark.parametrize("excerpt", [
    "Economics PhD application deadline: 2027-02-01. Academic year 2027.",
    "Economics PhD application deadline: 15 January 2027 or 1 February 2027.",
])
def test_wrong_or_alternative_admission_cutoffs_never_trigger(excerpt):
    invalid = {**row(), "evidence_excerpt": excerpt}
    assert eligible_official_admissions(catalog(invalid), now=NOW) == []
    assert not dispatch(invalid)


def test_same_delivery_key_with_two_different_university_programmes_is_held():
    first = row()
    second = {
        **first,
        "official_programme_url": "https://berlinschoolofeconomics.de/phd-program/economics",
        "evidence_url": "https://berlinschoolofeconomics.de/phd-program/economics",
        "deadline_iso": "2027-02-01",
        "evidence_excerpt": "Economics PhD application deadline: 1 February 2027",
    }
    assert eligible_official_admissions(catalog(first, second), now=NOW) == []
    assert not dispatch(first, second)


@pytest.mark.parametrize("invalid", [[], {}, "untrusted", 17])
def test_invalid_official_country_details_cannot_crash_recovery(invalid):
    bad = row()
    bad.update(
        institution="Barcelona School of Economics", country_code="ES",
        official_programme_url=BSE, evidence_url=BSE,
        official_details=invalid, investigated_urls=[BSE],
    )
    assert eligible_official_admissions(catalog(bad), now=NOW) == []
    assert not dispatch(bad)
