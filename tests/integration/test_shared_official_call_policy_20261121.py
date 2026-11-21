"""The official funding publisher and watchdog share one evidence contract."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from predoc_pipeline.publish.official_calls import eligible_calls
from tools.ingestion_watchdog import evaluate_official_calls_trigger

NOW = datetime(2026, 11, 21, 15, tzinfo=UTC)
HENLEY = "https://www.henley.ac.uk/study/phds/accounting-and-financial-management"
IEB = "https://ieb.ub.edu/en/phd-scholarship-in-economics-2027/"
RUNS = [{
    "name": "predoc-pipeline", "head_branch": "main",
    "status": "completed", "created_at": "2026-11-21T12:00:00Z",
}]
LEDGER = {"version": 1, "deliveries": {}}


def call():
    return {
        "source_id": "henley-accounting", "institution": "Henley Business School",
        "country_code": "UK", "kind": "phd_studentship",
        "title": "Accounting PhD Opportunities", "status": "verified",
        "intake_year": 2027,
        "official_url": HENLEY, "evidence_url": HENLEY,
        "evidence_excerpt": "Studentship applications close on 21 February 2027",
        "deadline_iso": "2027-02-21", "deadline_kind": "funding",
        "location_evidence_url": HENLEY,
        "location_evidence": "UK: official national institutional domain henley.ac.uk",
        "checked_at": "2026-11-21T14:00:00Z",
    }


def catalog(*rows, summary=False):
    result = {"kind": "official_phd_call_observations", "version": 1,
              "calls": list(rows)}
    if summary:
        result.update(generated_at="2026-11-21T14:00:00Z", sources=[{
            "id": "henley-accounting", "institution": "Henley Business School",
            "index_url": HENLEY, "status": "ok", "mode": "detail",
            "checked_at": "2026-11-21T14:00:00Z",
        }])
    return result


def dispatch(rows, *, summary=False):
    return evaluate_official_calls_trigger(
        catalog(*rows, summary=summary), LEDGER, RUNS, now=NOW,
    ).dispatch


def test_valid_new_ieb_geography_proof_wakes_watchdog():
    row = call()
    row.update(
        source_id="ieb-economics-2027",
        institution="Barcelona Institute of Economics (IEB)",
        country_code="ES", kind="phd_scholarship",
        title="PhD Scholarship in Economics 2027", official_url=IEB,
        evidence_url=IEB, location_evidence_url=IEB,
        location_evidence="ES: official IEB and University of Barcelona institutional identifiers",
        deadline_iso="2026-12-11", deadline_kind="scholarship",
        evidence_excerpt="Interested candidates must complete both steps by 11 December 2026",
    )
    assert eligible_calls(catalog(row), now=NOW) == [row]
    assert dispatch([row])


@pytest.mark.parametrize("excerpt", [
    "Studentship applications close on 21 February 2028. Academic year 2027.",
    "Studentship applications close on 21 February 2027 or 30 March 2027",
    "Studentship application deadline 2027-01-15; academic year 2027.",
])
def test_incorrect_or_conflicting_evidence_dates_fail_for_every_consumer(excerpt):
    row = {**call(), "evidence_excerpt": excerpt}
    assert eligible_calls(catalog(row), now=NOW) == []
    assert not dispatch([row])


@pytest.mark.parametrize("field,value", [
    ("posting_group", "henley-departmental-2027"),
    ("posting_group_expected", 5),
    ("recommended_admission_iso", "2027-01-15"),
    ("eligibility_scope", "home_only"),
    ("funding_scope", "home_rate_tuition"),
])
def test_duplicate_identity_with_conflicting_terms_is_held(field, value):
    first = call()
    second = {**first, field: value}
    assert eligible_calls(catalog(first, second), now=NOW) == []
    assert not dispatch([first, second])


def test_generated_catalogue_requires_approved_source_identity_and_host():
    row = call()
    assert eligible_calls(catalog(row, summary=True), now=NOW) == [row]
    assert dispatch([row], summary=True)
    invalid = deepcopy(row)
    invalid["source_id"] = "unapproved-institution"
    assert eligible_calls(catalog(invalid, summary=True), now=NOW) == []
    assert not dispatch([invalid], summary=True)
    bad_host = deepcopy(row)
    bad_host.update(official_url="https://another.ac.uk/study/phd",
                    evidence_url="https://another.ac.uk/study/phd",
                    location_evidence_url="https://another.ac.uk/study/phd",
                    location_evidence="UK: official national institutional domain another.ac.uk")
    assert eligible_calls(catalog(bad_host, summary=True), now=NOW) == []
    assert not dispatch([bad_host], summary=True)


def test_blocked_source_cannot_have_publishable_verified_row():
    bad = catalog(call(), summary=True)
    bad["sources"][0]["status"] = "robots_unavailable"
    assert eligible_calls(bad, now=NOW) == []
    assert not evaluate_official_calls_trigger(bad, LEDGER, RUNS, now=NOW).dispatch


def test_incomplete_generated_provenance_cannot_bypass_source_review():
    bad = catalog(call(), summary=True)
    bad["sources"].clear()
    assert eligible_calls(bad, now=NOW) == []
    assert not evaluate_official_calls_trigger(bad, LEDGER, RUNS, now=NOW).dispatch
