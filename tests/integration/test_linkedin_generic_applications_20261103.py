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
])
def test_reviewed_generic_employer_career_pages_are_not_individual_apply_links(url):
    assert application_url_issue(url) == "generic-employer-careers-page"


@pytest.mark.parametrize("url", [
    "https://rb.wd5.myworkdayjobs.com/FRS/job/Dallas-TX/Research-Analyst_R-0000032835-1",
    "https://www.jobs.lse.ac.uk/Vacancies/W/1234/0/43211/Research-Fellow",
    "https://www.fnuniv.ca/careers/jobs/real-specific-vacancy",
    "https://www.lse.ac.uk/LSEJobs/Current-vacancies/role-123",
    "https://www.jobbnorge.no/ledige-stillinger/stilling/309437/postdoktor-i-klima-og-miljoestyring",
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
