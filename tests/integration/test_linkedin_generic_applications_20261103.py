"""Regression coverage for LinkedIn-origin generic application destinations.

A broad career index is not a confirmed application for an individual vacancy.
Do not alter durable identities, dates or send receipts while withholding these
links from the public actionable listing projection.
"""
from __future__ import annotations

import pytest

from predoc_pipeline import state
from predoc_pipeline.core.output_quality import application_url_issue


@pytest.mark.parametrize("url", [
    "https://www.jobs.lse.ac.uk/",
    "https://www.lse.ac.uk/LSEJobs",
    "https://www.fnuniv.ca/",
    "https://rb.wd5.myworkdayjobs.com/FRS",
    "https://rb.wd5.myworkdayjobs.com/FRS/",
    # Live LinkedIn-origin Collegeum listing 441: only a careers homepage.
    "https://jobs.illinois.edu/",
    "https://jobs.illinois.edu",
])
def test_reviewed_generic_employer_career_pages_are_not_individual_apply_links(url):
    assert application_url_issue(url) == "generic-employer-careers-page"


@pytest.mark.parametrize("url", [
    "https://rb.wd5.myworkdayjobs.com/FRS/job/Dallas-TX/Research-Analyst_R-0000032835-1",
    "https://www.jobs.lse.ac.uk/Vacancies/W/1234/0/43211/Research-Fellow",
    "https://www.fnuniv.ca/careers/jobs/real-specific-vacancy",
    "https://www.lse.ac.uk/LSEJobs/Current-vacancies/role-123",
    "https://www.jobbnorge.no/ledige-stillinger/stilling/309437/postdoktor-i-klima-og-miljoestyring",
    # Distinct position path on the same host must not be blanket-rejected.
    "https://jobs.illinois.edu/job/example-requisition-id",
])
def test_position_specific_paths_are_not_rejected_as_generic(url):
    assert application_url_issue(url) is None


def test_generic_application_is_hidden_without_erasing_receipt_or_identity():
    generic = {
        "url_hash": "a" * 64,
        "apply_url": "https://rb.wd5.myworkdayjobs.com/FRS",
        "source_url": "https://www.linkedin.com/jobs/view/4455348498",
        "status": "published",
        "telegram_message_id": 402,
        "summary": "Academic research analyst job, but no requisition deep link.",
    }
    direct = {
        **generic,
        "url_hash": "b" * 64,
        "apply_url": "https://rb.wd5.myworkdayjobs.com/FRS/job/Dallas-TX/Research-Analyst_R-0000032835-1",
        "telegram_message_id": 403,
    }

    class Database:
        def active_listings(self):
            return [generic, direct]

    assert state._web_rows(Database(), set(), None) == [direct]
    assert generic["telegram_message_id"] == 402
    assert generic["source_url"].endswith("4455348498")


def test_illinois_generic_link_never_becomes_an_actionable_public_link():
    """LinkedIn listing 441 may remain in history without a fake 'Apply' link."""
    generic = {
        "url_hash": "c" * 64,
        "apply_url": "https://jobs.illinois.edu/",
        "source_url": "https://www.linkedin.com/jobs/view/4487018503",
        "status": "published",
        "telegram_delivery_state": "confirmed",
        "telegram_message_id": 441,
        "summary": "Postdoctoral economics role with unverified application deep link.",
    }
    direct = {
        **generic,
        "url_hash": "d" * 64,
        "apply_url": "https://jobs.illinois.edu/job/example-requisition-id",
        "telegram_message_id": 442,
    }

    class Database:
        def active_listings(self):
            return [generic, direct]

    assert state._web_rows(Database(), set(), None) == [direct]
    assert generic["telegram_delivery_state"] == "confirmed"
    assert generic["telegram_message_id"] == 441
    assert generic["source_url"].endswith("/4487018503")
