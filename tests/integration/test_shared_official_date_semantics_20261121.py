"""Prevent matching an opening/irrelevant date as an official submission cutoff.

One shared source policy must accept unambiguous opening + closing schedules
without silently promoting an opening date or a different legal cutoff.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from predoc_pipeline.publish.admissions import eligible_official_admissions
from predoc_pipeline.publish.official_calls import eligible_calls
from tools.ingestion_watchdog import (
    evaluate_admissions_trigger,
    evaluate_official_calls_trigger,
)

NOW = datetime(2026, 11, 21, 15, tzinfo=UTC)
RUNS = [{
    "name": "predoc-pipeline", "head_branch": "main",
    "status": "completed", "created_at": "2026-11-21T12:00:00Z",
}]
LEDGER = {"version": 1, "deliveries": {}}
FUNDING_URL = "https://www.henley.ac.uk/study/phds/accounting-and-financial-management"
ADMISSIONS_URL = "https://berlinschoolofeconomics.de/phd-program/application"


def funding(*, excerpt: str, deadline: str = "2027-02-21") -> dict:
    return {
        "source_id": "henley-accounting", "institution": "Henley Business School",
        "country_code": "UK", "kind": "phd_studentship",
        "title": "Accounting PhD Opportunities", "status": "verified",
        "intake_year": 2027, "deadline_iso": deadline,
        "official_url": FUNDING_URL, "evidence_url": FUNDING_URL,
        "location_evidence_url": FUNDING_URL,
        "location_evidence": "UK: official national institutional domain henley.ac.uk",
        "deadline_kind": "funding", "evidence_excerpt": excerpt,
        "checked_at": "2026-11-21T14:00:00Z",
    }


def admissions(*, excerpt: str, deadline: str = "2027-01-15") -> dict:
    return {
        "institution": "Berlin School of Economics", "country_code": "DE",
        "official_programme_url": ADMISSIONS_URL, "evidence_url": ADMISSIONS_URL,
        "status": "verified", "checked_at": "2026-11-21T14:00:00Z",
        "deadline_iso": deadline, "evidence_excerpt": excerpt,
    }


def funding_eligible(row: dict) -> bool:
    data = {"kind": "official_phd_call_observations", "version": 1, "calls": [row]}
    return eligible_calls(data, now=NOW) == [row]


def funding_dispatch(row: dict) -> bool:
    data = {"kind": "official_phd_call_observations", "version": 1, "calls": [row]}
    return evaluate_official_calls_trigger(data, LEDGER, RUNS, now=NOW).dispatch


def admissions_eligible(row: dict) -> bool:
    data = {
        "kind": "economics_phd_admissions_observations",
        "scope": "official_programme_sources_only",
        "source": {"deadline_values_reused": False}, "programmes": [row],
    }
    return eligible_official_admissions(data, now=NOW) == [row]


def admissions_dispatch(row: dict) -> bool:
    data = {
        "kind": "economics_phd_admissions_observations",
        "scope": "official_programme_sources_only",
        "source": {"deadline_values_reused": False}, "programmes": [row],
    }
    return evaluate_admissions_trigger(data, LEDGER, RUNS, now=NOW).dispatch


def test_funding_schedule_open_and_close_dates_are_not_ambiguous():
    row = funding(excerpt=(
        "Studentship applications open on 1 December 2026 and close on "
        "21 February 2027."
    ))
    assert funding_eligible(row)
    assert funding_dispatch(row)


def test_admissions_schedule_open_and_close_dates_are_not_ambiguous():
    row = admissions(excerpt=(
        "PhD admissions applications open on 1 December 2026 and close on "
        "15 January 2027."
    ))
    assert admissions_eligible(row)
    assert admissions_dispatch(row)


@pytest.mark.parametrize("text", [
    "Studentship applications open on 21 February 2027; closing date to be announced.",
    "Applications open on 21 February 2027. Scholarship application closing date TBD.",
    "Studentship opens on 21 February 2027 and closes in March, date TBA.",
])
def test_funding_opening_date_can_never_be_published_as_deadline(text):
    row = funding(excerpt=text)
    assert not funding_eligible(row)
    assert not funding_dispatch(row)


@pytest.mark.parametrize("text", [
    "PhD admissions open on 15 January 2027; closing date to be announced.",
    "Applications open on 15 January 2027; admission deadline will be published later.",
    "Admissions begins 15 January 2027 but closes in March, date TBA.",
])
def test_admissions_opening_date_can_never_be_published_as_deadline(text):
    row = admissions(excerpt=text)
    assert not admissions_eligible(row)
    assert not admissions_dispatch(row)


@pytest.mark.parametrize("text", [
    "Doctoral orientation is 21 February 2027; studentship deadline pending.",
    "The institution will notify applicants on 21 February 2027; funding closes later.",
])
def test_unrelated_date_cannot_be_used_as_funding_cutoff(text):
    row = funding(excerpt=text)
    assert not funding_eligible(row)
    assert not funding_dispatch(row)


@pytest.mark.parametrize("generated", [
    "2025-11-21T14:00:00Z", "2026-11-22T14:00:00Z", "invalid-date",
])
def test_generated_catalogue_cannot_fake_freshness(generated):
    row = funding(excerpt="Studentship applications close on 21 February 2027.")
    data = {
        "kind": "official_phd_call_observations", "version": 1,
        "generated_at": generated,
        "sources": [{
            "id": "henley-accounting", "institution": "Henley Business School",
            "mode": "detail", "status": "ok", "index_url": FUNDING_URL,
            "checked_at": "2026-11-21T14:00:00Z",
        }],
        "calls": [row],
    }
    assert eligible_calls(data, now=NOW) == []
    assert not evaluate_official_calls_trigger(data, LEDGER, RUNS, now=NOW).dispatch
