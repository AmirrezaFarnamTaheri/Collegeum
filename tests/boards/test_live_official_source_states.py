"""Production source regressions verified against live official pages on 2026-10-29.

An actual career directory with no targeted job links is legitimately empty,
but arbitrary successful HTTP responses must never be treated as healthy.
"""

import asyncio
from datetime import date
from pathlib import Path

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS
from predoc_pipeline.core.health import source_status


def source(name):
    return next(
        cfg for cfg in load_board_sources(Path("config/sources.toml"))
        if cfg.name == name
    )


class FixtureHttp:
    def __init__(self, expected_url, html):
        self.expected_url = expected_url
        self.html = html

    async def get_text(self, url):
        assert url == self.expected_url
        return self.html


def collect(name, html):
    cfg = source(name)
    result = asyncio.run(_scrape_all([
        SCRAPERS[cfg.type](cfg, FixtureHttp(cfg.opt("url"), html))
    ], 1, 5))[0]
    return result


def test_ny_fed_canonical_index_avoids_http_200_redirect_to_error_page(monkeypatch):
    monkeypatch.setattr("predoc_pipeline.boards.scrapers.link_scan.today",
                        lambda: date(2026, 10, 29))
    """The path without /index currently returns the NY Fed's /errors/500 page."""
    cfg = source("ny_fed")
    assert cfg.opt("url") == (
        "https://www.newyorkfed.org/research/careers/research_analysts/index"
    )
    html = """
      <h1>Research Analysts</h1><table><tr>
      <td>Research Analyst</td><td>Summer 2027</td>
      <td>2 years</td><td>Aug. 24 – Sept. 14</td>
      </tr></table>
    """
    result = collect("ny_fed", html)
    assert result.ok
    assert result.posts == []
    assert source_status(result.as_stats()) == "empty"


def test_iies_live_directory_only_with_tenure_track_notice_is_valid_empty():
    """The live October page changed its introductory faculty recruitment text."""
    cfg = source("iies_stockholm")
    assert cfg.opt("verified_empty_marker") == (
        "You can search for available positions at Stockholm University at the central website"
    )
    html = """
      <h1>Work with us</h1>
      <p>You can search for available positions at Stockholm University at the
      central website:</p>
      <a href="https://www.su.se/english/about-the-university/work-at-su/available-jobs">
        Available jobs at Stockholm University</a>
      <h2>Tenure-track Assistant Professor</h2>
      <p>The Institute for International Economic Studies seeks to recruit
      at the tenure-track assistant professor level.</p>
    """
    result = collect("iies_stockholm", html)
    assert result.ok and result.posts == []
    assert source_status(result.as_stats()) == "empty"


def test_iies_unrecognized_replacement_page_remains_a_source_error():
    result = collect("iies_stockholm", "<h1>University news</h1><p>Page moved</p>")
    assert not result.ok
    assert result.as_stats()["failure_counts"]["parse"] >= 1


def test_opportunity_insights_verified_no_current_job_links_is_empty():
    """Live official career page no longer links to its previous job-description PDF."""
    cfg = source("opportunity_insights")
    assert cfg.may_be_empty is True
    assert cfg.opt("verified_empty_marker") == "Keep an eye on our openings"
    html = """
      <h1>Join Our Team</h1>
      <p>Thank you for your interest in Opportunity Insights.</p>
      <p>Interested in joining our team? Keep an eye on our openings</p>
    """
    result = collect("opportunity_insights", html)
    assert result.ok and result.posts == []
    assert source_status(result.as_stats()) == "empty"


def test_opportunity_insights_arbitrary_non_careers_page_is_not_valid_empty():
    result = collect("opportunity_insights", "<h1>New research report</h1>")
    assert not result.ok
    assert source_status(result.as_stats()) == "failed"


def test_opportunity_insights_discovers_new_official_harvard_academic_posting():
    """Harvard's ARIeS portal has carried an OI predoctoral recruitment link."""
    href = "https://academicpositions.harvard.edu/postings/16734"
    html = (
        "<h1>Join Our Team</h1><p>Keep an eye on our openings</p>"
        f'<a href="{href}">Predoctoral Fellowship — Opportunity Insights</a>'
    )
    result = collect("opportunity_insights", html)
    assert result.ok
    assert [p.url for p in result.posts] == [href]


def test_opportunity_insights_unrecognized_application_link_cannot_look_empty():
    """A new applicant-tracking host must alert until verified and admitted."""
    html = (
        "<h1>Join Our Team</h1><p>Keep an eye on our openings</p>"
        '<a href="https://hiring.example.org/positions/123">'
        'Predoctoral Research Fellow — Opportunity Insights</a>'
    )
    result = collect("opportunity_insights", html)
    assert not result.ok
    assert result.posts == []
    assert result.as_stats()["failure_counts"]["parse"] >= 1


def test_opportunity_insights_harvard_hostname_spoof_is_not_an_advert():
    html = (
        "<h1>Join Our Team</h1><p>Keep an eye on our openings</p>"
        '<a href="https://academicpositions.harvard.edu.evil.invalid/postings/16734">'
        'Predoctoral Fellowship — Opportunity Insights</a>'
    )
    result = collect("opportunity_insights", html)
    assert result.posts == []
    assert not result.ok


def test_opportunity_insights_recruiting_sentence_on_new_host_blocks_empty():
    """Hiring messages are job signals even if the label is not a job title."""
    html = (
        "<h1>Join Our Team</h1><p>Keep an eye on our openings</p>"
        '<a href="https://hiring.example.org/opportunity/123">'
        'We are hiring predoctoral researchers this winter</a>'
    )
    result = collect("opportunity_insights", html)
    assert result.posts == []
    assert not result.ok
    assert source_status(result.as_stats()) == "failed"


def test_opportunity_insights_new_postdoctoral_fellowship_link_blocks_empty():
    html = (
        "<h1>Join Our Team</h1><p>Keep an eye on our openings</p>"
        '<a href="https://hiring.example.org/opportunity/456">'
        'Now recruiting postdoctoral fellows</a>'
    )
    result = collect("opportunity_insights", html)
    assert result.posts == []
    assert not result.ok
    assert source_status(result.as_stats()) == "failed"
