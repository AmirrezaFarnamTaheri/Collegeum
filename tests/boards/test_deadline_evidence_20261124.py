"""Cutoff dates require evidence; posting ages retain their separate contract."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from predoc_pipeline.boards.config import SourceConfig
from predoc_pipeline.boards.heuristics import apply_heuristics, check_still_open
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper
from predoc_pipeline.boards.scrapers.predoc_org import PredocOrgScraper
from predoc_pipeline.boards.scrapers.prospective_jobs import _employer_application_cutoff
from predoc_pipeline.boards.utils.dates import (
    extract_deadline,
    parse_date,
    parse_deadline_date,
    parse_posted,
)

REF = date(2026, 11, 24)


@pytest.mark.parametrize("value, expected", [
    ("2027-01-15", date(2027, 1, 15)),
    ("January 15, 2027", date(2027, 1, 15)),
    ("15th of January, 2027 at 23:59 UTC", date(2027, 1, 15)),
    ("15. janvier 2027", date(2027, 1, 15)),
    ("15 januar 2027", date(2027, 1, 15)),
    ("15/01/2027", date(2027, 1, 15)),
    ("01/15/2027", date(2027, 1, 15)),
    ("15.01.2027", date(2027, 1, 15)),
    ("15-01-2027", date(2027, 1, 15)),
    ("11/11/2027", date(2027, 11, 11)),
    ("29 February 2028", date(2028, 2, 29)),
    ("January 15, 2027 (2027-01-15)", date(2027, 1, 15)),
])
def test_explicit_unambiguous_cutoffs(value, expected):
    assert parse_deadline_date(value) == expected
    assert extract_deadline(f"Application deadline: {value}", REF)[0] == expected


@pytest.mark.parametrize("value", [
    "15 January", "January 15", "01 Oct", "15/01", "5/24/27",
    "03/04/2027", "03.04.2027", "03-04-2027", "15/01-2027",
    "2027-15-01", "2027-02-29", "31 April 2027", "00/01/2027",
    "13/14/2027", "January 15, 20270", "January 15; 2027 intake",
    "January 15 or February 1, 2027", "January 15, 2027 or February 1",
    "January 15, 2027 or February 1, 2027",
    "from January 15, 2027 to February 1, 2027",
    "03/04/2027 (May 1, 2027)",
])
def test_incomplete_ambiguous_and_invalid_cutoffs_remain_unknown(value):
    assert parse_deadline_date(value) is None
    for ref in (date(2020, 1, 1), REF, date(2030, 12, 31)):
        assert extract_deadline(f"Application deadline: {value}", ref)[0] is None


@pytest.mark.parametrize("value", ["15 January", "03/04/2027", "January 15 or February 1, 2027"])
def test_unconfirmed_cutoff_retains_verbatim_evidence(value):
    text = f"Application deadline: {value}"
    assert extract_deadline(text, REF) == (None, text)


def test_start_date_cannot_supply_the_missing_deadline_year():
    value, note = extract_deadline("Deadline: 15 January. Start date: 1 March 2027.", REF)
    assert value is None
    assert note == "Deadline: 15 January."


@pytest.mark.parametrize("text, days", [
    ("Posted Today", 0), ("Just now", 0), ("Posted 3 minutes ago", 0),
    ("Posted an hour ago", 0), ("Posted Yesterday", 1),
    ("Posted 3 days ago", 3), ("Posted 30+ days ago", 30),
    ("Posted a week ago", 7), ("Posted 2 weeks ago", 14),
    ("Posted one month ago", 30), ("Posted 2 months ago", 60),
])
def test_relative_posting_dates_are_unchanged(text, days):
    assert parse_posted(text, REF) == REF - timedelta(days=days)


def test_general_and_posting_parsers_retain_legacy_date_support():
    assert parse_date("01 Oct", REF) == date(2026, 10, 1)
    assert parse_posted("Posted 01 Oct", REF) == date(2026, 10, 1)
    assert parse_date("5/24/27", REF) == date(2027, 5, 24)
    assert parse_posted("Posted 03/04/2027", REF) == date(2027, 4, 3)


def post():
    return JobPostSchema(
        title="Research Assistant in Economics", institution="Example University",
        source="offline-test", url="https://example.test/jobs/1",
    )


@pytest.mark.parametrize("cutoff", ["January 15", "03/04/2027"])
def test_shared_enrichment_cannot_promote_uncertain_deadline(cutoff):
    item = post()
    text = f"Application deadline: {cutoff}."
    apply_heuristics(item, text)
    assert item.deadline is None
    assert item.deadline_text == text


@pytest.mark.parametrize("cutoff, expected_closed", [
    ("January 15", False), ("03/04/2026", False), ("January 15, 2026", True),
])
def test_uncertain_cutoff_cannot_expire_a_job(monkeypatch, cutoff, expected_closed):
    monkeypatch.setattr("predoc_pipeline.boards.utils.dates.today", lambda: REF)

    class OfflineScraper:
        async def fetch_detail(self, item):
            return f"Application deadline: {cutoff}."

    result = asyncio.run(check_still_open(OfflineScraper(), post()))
    assert bool(result) is expected_closed


@pytest.mark.parametrize("cutoff, expected", [
    ("January 15", None), ("03/04/2027", None), ("5/24/27", None),
    ("January 15, 2027", date(2027, 1, 15)),
])
def test_predoc_deadline_cell_uses_strict_parser(cutoff, expected):
    scraper = PredocOrgScraper(SourceConfig(name="offline", type="predoc_org"), None)
    html = (
        '<h2><a href="https://example.test/jobs/1">Research Assistant in Economics</a></h2>'
        '<p>Sponsoring Institution: Example University</p>'
        f'<p>Deadline: {cutoff}</p>'
    )
    item, = scraper.parse_postings([("https://predoc.org/opportunities", html)])
    assert item.deadline == expected
    assert item.deadline_text == cutoff


@pytest.mark.parametrize("cutoff, expected", [
    ("January 15", None), ("03/04/2027", None),
    ("January 15, 2027; February 1, 2027", None),
    ("First review date: January 15, 2027", None),
    ("Priority deadline: January 15, 2027", None),
    ("Deadline: not stated. Start date: January 15, 2027", None),
    ("2027-01-15", date(2027, 1, 15)), ("15/01/2027", date(2027, 1, 15)),
])
def test_bare_board_cell_cannot_bypass_deadline_evidence(cutoff, expected):
    scraper = LinkScanScraper(SourceConfig(
        name="offline", type="link_scan", institution="Example University",
        link_pattern=r"example\.test/jobs/\d+", bare_date_is_deadline=True,
    ), None)
    html = (
        '<article><h2><a href="https://example.test/jobs/1">Research Assistant in Economics</a></h2>'
        f'<p>{cutoff}</p></article>'
    )
    item, = scraper.parse_postings([("https://example.test/jobs", html)])
    assert item.deadline == expected


@pytest.mark.parametrize("cutoff, expected", [
    ("03/04/2027", None), ("15/01/2027", date(2027, 1, 15)),
    ("2027-01-15", date(2027, 1, 15)),
])
def test_bern_submission_fallback_cannot_guess_numeric_order(cutoff, expected):
    text = f"Please submit your application including your CV and references by {cutoff}."
    assert _employer_application_cutoff(text) == expected


@pytest.mark.parametrize("label, value", [
    ("First review date", "January 15, 2027"),
    ("Review date", "January 15, 2027"),
    ("Priority deadline", "January 15, 2027"),
    ("Priority application deadline", "January 15, 2027"),
    ("Deadline/First Review Date", "January 15, 2027"),
    ("Deadline", "First review date January 15, 2027, then rolling"),
    ("Deadline", "Priority deadline January 15, 2027"),
    ("Deadline", "January 15, 2027 for full consideration"),
])
def test_predoc_review_dates_do_not_become_final_cutoffs(label, value):
    scraper = PredocOrgScraper(SourceConfig(name="offline", type="predoc_org"), None)
    html = (
        '<h2><a href="https://example.test/jobs/1">Research Assistant in Economics</a></h2>'
        '<p>Sponsoring Institution: Example University</p>'
        f'<p>{label}: {value}</p>'
    )
    item, = scraper.parse_postings([("https://predoc.org/opportunities", html)])
    assert item.deadline is None
    assert value in item.deadline_text
    assert value in item.extra["predoc_review_note"]
    assert f"{label}: {value}" in item.description_snippet
    # The source's summary is subsequently read by the shared enrichment path.
    # Keeping the original role must also prevent a second-pass promotion.
    apply_heuristics(item, item.description_snippet)
    assert item.deadline is None


@pytest.mark.parametrize("label", [
    "Deadline", "Application deadline", "Closing date", "Final application deadline",
])
def test_predoc_distinct_final_deadline_wins_without_erasing_review_note(label):
    scraper = PredocOrgScraper(SourceConfig(name="offline", type="predoc_org"), None)
    html = (
        '<h2><a href="https://example.test/jobs/1">Research Assistant in Economics</a></h2>'
        '<p>Sponsoring Institution: Example University</p>'
        '<p>First review date: January 15, 2027</p>'
        f'<p>{label}: February 1, 2027</p>'
    )
    item, = scraper.parse_postings([("https://predoc.org/opportunities", html)])
    assert item.deadline == date(2027, 2, 1)
    assert item.deadline_text == "February 1, 2027"
    assert item.extra["predoc_review_note"] == "First review date: January 15, 2027"


def test_predoc_mixed_label_requires_explicit_application_closing_evidence():
    scraper = PredocOrgScraper(SourceConfig(name="offline", type="predoc_org"), None)
    html = (
        '<h2><a href="https://example.test/jobs/1">Research Assistant in Economics</a></h2>'
        '<p>Sponsoring Institution: Example University</p>'
        '<p>Deadline/First Review Date: January 15, 2027; applications close on February 1, 2027</p>'
    )
    item, = scraper.parse_postings([("https://predoc.org/opportunities", html)])
    assert item.deadline == date(2027, 2, 1)
    assert "January 15, 2027" in item.extra["predoc_review_note"]
    assert "applications close on February 1, 2027" in item.deadline_text


@pytest.mark.parametrize("text", [
    "Priority deadline: January 15, 2027",
    "Priority application deadline: January 15, 2027",
    "Priority consideration date: January 15, 2027",
    "Apply by January 15, 2027 for full consideration.",
])
def test_shared_priority_timing_retains_evidence_without_hard_cutoff(text):
    assert extract_deadline(text, REF) == (None, text)


@pytest.mark.parametrize("value", [
    "January 15, 2027 or 15/02",
    "15/02 or January 15, 2027",
    "January 15, 2027 or 15.02",
    "January 15, 2027 or 15-02",
    "January 15, 2027 or February 2027",
    "January 15, 2027 or 2027-02",
    "January 15, 2027 or 2027-02-29",
    "January 15, 2027 or 2027-15-01",
    "2027-01-15/16",
])
def test_partial_or_invalid_alternative_cannot_be_discarded(value):
    assert parse_deadline_date(value) is None
    cutoff, evidence = extract_deadline(f"Application deadline: {value}")
    assert cutoff is None
    assert evidence is not None


@pytest.mark.parametrize("text", [
    "Application deadline: January 15, 2027. Application deadline: February 1, 2027.",
    "Domestic application deadline: January 15, 2027. "
    "International application deadline: February 1, 2027.",
    "Application deadline: January 15, 2027. Application deadline: February 1.",
    "Application deadline: 15/02. Applications close on January 15, 2027.",
    "Application deadline: January 15, 2027. Applications close on 2027-02-29.",
    "Application deadline: January 15, 2027 " + "(please use the online application form) " * 3
    + "or February 1, 2027.",
])
def test_every_relevant_cutoff_is_checked_before_confirmation(text):
    cutoff, evidence = extract_deadline(text)
    assert cutoff is None
    assert evidence is not None
    assert extract_deadline(evidence)[0] is None
    item = post()
    apply_heuristics(item, text)
    assert item.deadline is None


@pytest.mark.parametrize("text", [
    "For full consideration, apply by January 15, 2027.",
    "For priority consideration, application deadline: January 15, 2027.",
    "Apply by January 15, 2027 to receive full consideration.",
    "Application deadline (priority): January 15, 2027.",
    "Application deadline: January 15, 2027 (priority).",
    "Application deadline: January 15, 2027 (first review).",
    "Application deadline: January 15, 2027 [first review].",
    "First review, Application deadline: January 15, 2027.",
    "Application deadline: January 15, 2027 " + "(please use the online application form) " * 3
    + "for full consideration.",
])
def test_nonfinal_qualifier_order_cannot_create_a_hard_cutoff(text):
    cutoff, evidence = extract_deadline(text)
    assert cutoff is None
    assert evidence is not None
    assert "January 15, 2027" in evidence
    assert extract_deadline(evidence)[0] is None
    item = post()
    apply_heuristics(item, text)
    assert item.deadline is None


@pytest.mark.parametrize("text", [
    "Application deadline: January 15, 2027. Applications close on 2027-01-15.",
    "First review date: December 1, 2026; applications close on January 15, 2027.",
    "Priority deadline: December 1, 2026. Final application deadline: January 15, 2027.",
    "Review date: December 1, 2026. Final application deadline: January 15, 2027.",
    "Application deadline: January 15, 2027. First review date: January 20, 2027.",
])
def test_repeated_cutoff_and_separate_review_roles_keep_the_final_date(text):
    assert extract_deadline(text)[0] == date(2027, 1, 15)


@pytest.mark.parametrize("following", [
    "Requirements: 1-2 years of research experience.",
    "Qualifications: 1-2 years of research experience.",
    "Experience: 1-2 years in a university.",
    "Work schedule: 2/3 days each week.",
    "Salary: grade 2/3.",
    "Contact: room 1/2, Example University.",
    "Funding deadline: February 1, 2027.",
])
def test_other_labelled_sections_do_not_supply_competing_cutoffs(following):
    text = f"Application deadline: January 15, 2027. {following}"
    assert extract_deadline(text)[0] == date(2027, 1, 15)


def test_other_section_does_not_hide_a_later_application_cutoff():
    text = (
        "Application deadline: January 15, 2027. Requirements: 1-2 years of research experience. "
        "Application deadline: February 1, 2027."
    )
    assert extract_deadline(text)[0] is None


@pytest.mark.parametrize("application", [
    "Please submit by 15 January 2027 or 1 February 2027.",
    "Please submit your application including your CV by 15 January 2027 or 01/02.",
    "Please submit your application including your CV by 15 January 2027 or 1 February 2027.",
    "Please submit your application including your CV by 15 January 2027 for full consideration.",
    "Please submit your application for full consideration including your CV by 15 January 2027.",
    "For full consideration, apply by January 15, 2027.",
    "Application deadline: January 15, 2027 (first review).",
])
def test_bern_rejected_cutoff_stays_unknown_through_enrichment_and_eligibility(application):
    from predoc_pipeline.boards.scrapers.prospective_jobs import ProspectiveJobsScraper
    from predoc_pipeline.ingest.life_sciences import classify_post
    from tests.boards.test_bern_prospective_api_20261031 import FakeHttp, _config, _job

    assert _employer_application_cutoff(application) is None
    job = _job(deadline=None)
    job["szas"]["sza_application"] = application
    item, = ProspectiveJobsScraper(_config(), FakeHttp({})).parse_postings([job])
    assert item.deadline is None
    assert not item.extra.get("prospective_employer_deadline_verified")
    apply_heuristics(item, item.description_snippet)
    assert item.deadline is None
    assert classify_post(item, today=REF) is None


@pytest.mark.parametrize("second", [
    "Application deadline: February 1, 2027",
    "Closing date: February 1",
    "Final deadline: 15/02",
])
def test_predoc_preserves_conflicting_or_incomplete_cutoff_fields(second):
    scraper = PredocOrgScraper(SourceConfig(name="offline", type="predoc_org"), None)
    html = (
        '<h2><a href="https://example.test/jobs/1">Research Assistant in Economics</a></h2>'
        '<p>Sponsoring Institution: Example University</p>'
        '<p>Deadline: January 15, 2027</p>'
        f'<p>{second}</p>'
    )
    item, = scraper.parse_postings([("https://predoc.org/opportunities", html)])
    assert item.deadline is None
    assert "January 15, 2027" in item.deadline_text
    assert second in item.deadline_text
    assert second in item.description_snippet
    apply_heuristics(item, item.description_snippet)
    assert item.deadline is None


@pytest.mark.parametrize("prefix", [
    "For full consideration, ", "For priority consideration, ", "First review, ",
])
def test_predoc_keeps_a_leading_review_qualifier_with_its_date(prefix):
    scraper = PredocOrgScraper(SourceConfig(name="offline", type="predoc_org"), None)
    html = (
        '<h2><a href="https://example.test/jobs/1">Research Assistant in Economics</a></h2>'
        '<p>Sponsoring Institution: Example University</p>'
        f'<p>{prefix}Deadline: January 15, 2027</p>'
    )
    item, = scraper.parse_postings([("https://predoc.org/opportunities", html)])
    assert item.institution == "Example University"
    assert item.deadline is None
    assert prefix in item.extra["predoc_review_note"]
    assert f"{prefix}Deadline: January 15, 2027" in item.description_snippet
    apply_heuristics(item, item.description_snippet)
    assert item.deadline is None


def test_predoc_retains_each_review_field_beside_a_distinct_final_cutoff():
    scraper = PredocOrgScraper(SourceConfig(name="offline", type="predoc_org"), None)
    html = (
        '<h2><a href="https://example.test/jobs/1">Research Assistant in Economics</a></h2>'
        '<p>Sponsoring Institution: Example University</p>'
        '<p>Priority deadline: December 1, 2026</p>'
        '<p>For full consideration, Deadline: December 15, 2026</p>'
        '<p>Final application deadline: January 15, 2027</p>'
    )
    item, = scraper.parse_postings([("https://predoc.org/opportunities", html)])
    assert item.deadline == date(2027, 1, 15)
    assert item.deadline_text == "January 15, 2027"
    assert "December 1, 2026" in item.extra["predoc_review_note"]
    assert "December 15, 2026" in item.extra["predoc_review_note"]
    assert "December 1, 2026" in item.description_snippet
    assert "December 15, 2026" in item.description_snippet
