"""Official DKFZ RSS verification must not depend on the obsolete HTML scanner."""
from __future__ import annotations

from datetime import date

import pytest

from predoc_pipeline.boards.models import JobPostSchema
from tools.verify_life_dkfz import assess_dkfz_probe


def _job(title: str, suffix: str, *, deadline: date | None = None) -> JobPostSchema:
    return JobPostSchema(
        title=title,
        url=f"https://jobs.dkfz.de/de/jobs/{suffix}",
        source="life_dkfz",
        institution="German Cancer Research Center (DKFZ)",
        location="Heidelberg",
        country="Germany",
        description_snippet="Research on epigenetic gene regulation and cancer biology.",
        deadline=deadline,
        extra={"require_deadline": True},
    )


def _health(*, status: str = "discovered", issues: int = 0, details: int = 0):
    return {"life_dkfz": {
        "status": status, "discovery_issues": issues, "detail_failures": details,
    }}


def test_rss_verifier_checks_employer_identity_and_only_counts_eligible_phds():
    jobs = [
        _job("PhD Student in Epigenetics", "170001/phd", deadline=date(2026, 11, 30)),
        _job("Postdoctoral Fellow in Genomics", "170002/postdoc"),
    ]
    report = assess_dkfz_probe(jobs, [], _health(), on_date=date(2026, 10, 31))
    assert report["source"] == "life_dkfz"
    assert report["general_vacancies"] == 2
    assert report["eligible_doctoral_matches"] == 1
    assert report["status"] == "discovered"


def test_rss_verifier_rejects_partial_and_failed_detail_collection():
    jobs = [_job("PhD Student in Epigenetics", "170001/phd")]
    with pytest.raises(RuntimeError):
        assess_dkfz_probe(jobs, [], _health(status="partial", details=1))
    with pytest.raises(RuntimeError):
        assess_dkfz_probe(jobs, ["source fetch failed"], _health(issues=1))


def test_rss_verifier_refuses_empty_or_foreign_job_urls():
    with pytest.raises(RuntimeError):
        assess_dkfz_probe([], [], _health())
    malicious = _job("PhD Student in Epigenetics", "170001/phd")
    malicious.url = "https://jobs.dkfz.de.attacker.invalid/de/jobs/170001/phd"
    with pytest.raises(RuntimeError):
        assess_dkfz_probe([malicious], [], _health())
