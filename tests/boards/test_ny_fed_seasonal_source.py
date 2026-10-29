"""The NY Fed's Research Analyst application window is seasonal.

Treat a missing job as legitimately empty only when the official 2027 RA row
is still present AND its application deadline has already passed. Never
confuse an unrelated internship notice or a navigation link with an RA job.
"""

import asyncio
from datetime import date
from pathlib import Path

import pytest

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS
from predoc_pipeline.core.health import source_status

CLOSED_INTERNSHIPS = (
    "Applications for intern positions with a summer 2027 start date are now closed."
)
RA_ROW = (
    "<tr><td>Research Analyst</td><td>Summer 2027</td>"
    "<td>2 years</td><td>Aug. 24 – Sept. 14</td></tr>"
)


@pytest.fixture(autouse=True)
def fixed_ny_fed_date(monkeypatch):
    """The seasonal checks must be deterministic beyond the 2027 guard window."""
    monkeypatch.setattr("predoc_pipeline.boards.scrapers.link_scan.today",
                        lambda: date(2026, 10, 29))


def source():
    return next(
        s for s in load_board_sources(Path("config/sources.toml"))
        if s.name == "ny_fed"
    )


class FixtureHttp:
    def __init__(self, html):
        self.html = html

    async def get_text(self, url):
        assert url == "https://www.newyorkfed.org/research/careers/research_analysts/index"
        return self.html


def scrape(html):
    cfg = source()
    return asyncio.run(
        _scrape_all([SCRAPERS[cfg.type](cfg, FixtureHttp(html))], 1, 5)
    )[0]


def test_closed_ra_application_window_is_a_verified_seasonal_empty():
    cfg = source()
    assert cfg.may_be_empty is True
    assert cfg.opt("verified_empty_marker") == "Research Analyst Summer 2027"
    assert cfg.opt("verified_empty_after") == "2026-09-14"
    assert cfg.opt("verified_empty_before") == "2027-08-01"
    html = f"<h1>Research Analysts</h1><table>{RA_ROW}</table><p>{CLOSED_INTERNSHIPS}</p>"
    result = scrape(html)
    assert result.ok
    assert result.posts == []
    assert result.as_stats()["errors"] == 0
    assert source_status(result.as_stats()) == "empty"


def test_changed_page_without_ra_cycle_notice_must_alert_not_silently_go_empty():
    result = scrape("<h1>Research Analysts</h1><p>New hiring cycle information</p>")
    assert result.posts == []
    assert not result.ok
    assert result.as_stats()["failure_counts"]["parse"] == 1
    assert source_status(result.as_stats()) == "failed"


def test_internships_closed_notice_does_not_conceal_a_new_ra_cycle():
    html = (
        "<table><tr><td>Research Analyst</td><td>Summer 2028</td>"
        "<td>2 years</td><td>Aug. 24 – Sept. 14</td></tr></table>"
        f"<p>{CLOSED_INTERNSHIPS}</p>"
    )
    result = scrape(html)
    assert not result.ok
    assert source_status(result.as_stats()) == "failed"


def test_old_ra_cycle_marker_expires_before_next_application_season(monkeypatch):
    monkeypatch.setattr("predoc_pipeline.boards.scrapers.link_scan.today",
                        lambda: date(2027, 8, 1))
    result = scrape(f"<table>{RA_ROW}</table>")
    assert not result.ok
    assert source_status(result.as_stats()) == "failed"


def test_careers_phd_navigation_link_never_becomes_a_vacancy():
    nav = '<a href="https://www.newyorkfed.org/research/careers/careers_phd">Careers: PhD</a>'
    result = scrape(nav)
    assert result.posts == []
    assert not result.ok
    assert result.as_stats()["failure_counts"]["parse"] == 1
    assert source_status(result.as_stats()) == "failed"

    result_with_notice = scrape(f"<table>{RA_ROW}</table>{nav}")
    assert result_with_notice.posts == []
    assert source_status(result_with_notice.as_stats()) == "empty"


def test_future_real_ny_fed_application_link_is_collected_without_closed_marker():
    href = (
        "https://recruiting.wd1.myworkdayjobs.com/FRS/job/New-York/"
        "Research-Analyst_R0000000"
    )
    html = f'<a href="{href}">Research Analyst – Economics Research</a>'
    result = scrape(html)
    assert result.ok
    assert [post.url for post in result.posts] == [href]
    assert source_status(result.as_stats()) == "successful"


def test_ra_deadline_changed_but_cohort_marker_kept_must_not_claim_empty():
    html = (
        "<table><tr><td>Research Analyst</td><td>Summer 2027</td>"
        "<td>2 years</td><td>Aug. 24 – Nov. 30</td></tr></table>"
    )
    result = scrape(html)
    assert result.posts == []
    assert not result.ok
    assert result.as_stats()["failure_counts"]["parse"] >= 1


def test_new_ra_cohort_row_alongside_expired_one_must_alert():
    html = (
        f"<table>{RA_ROW}"
        "<tr><td>Research Analyst</td><td>Summer 2028</td>"
        "<td>2 years</td><td>Aug. 25 – Sept. 15</td></tr></table>"
    )
    result = scrape(html)
    assert result.posts == []
    assert not result.ok
    assert source_status(result.as_stats()) == "failed"


def test_old_ra_marker_outside_the_cohort_row_is_not_no_vacancy_proof():
    result = scrape("<h1>Research Analyst Summer 2027</h1>")
    assert result.posts == []
    assert not result.ok
    assert source_status(result.as_stats()) == "failed"


def test_predoc_speech_link_does_not_masquerade_as_ny_fed_vacancy():
    """Regression: live NY Fed 2024 speech is not a 2026 job application."""
    speech = (
        '<a href="https://www.newyorkfed.org/newsevents/speeches/2024/are240711">'
        'spoke to pre-doctoral economics students</a>'
    )
    result = scrape(f"<h1>Research Analysts</h1><table>{RA_ROW}</table>{speech}")
    assert result.posts == []
    assert result.ok
    assert source_status(result.as_stats()) == "empty"


def test_research_analyst_interview_link_is_not_a_vacancy():
    """An article mentioning a job title does not automatically reopen hiring."""
    interview = (
        '<a href="https://www.newyorkfed.org/research/people/interview">'
        'Meet a research analyst at the NY Fed</a>'
    )
    result = scrape(f"<table>{RA_ROW}</table>{interview}")
    assert result.ok
    assert source_status(result.as_stats()) == "empty"


def test_real_unrecognized_predoc_application_link_blocks_empty_health():
    """Do not fix false positives by disabling detection of new hiring hosts."""
    new_hiring_link = (
        '<a href="https://hiring.example.org/opportunity/123">'
        'Predoctoral Research Fellow</a>'
    )
    result = scrape(f"<table>{RA_ROW}</table>{new_hiring_link}")
    assert result.posts == []
    assert not result.ok
    assert source_status(result.as_stats()) == "failed"
