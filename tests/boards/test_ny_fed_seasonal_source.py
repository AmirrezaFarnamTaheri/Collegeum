"""The NY Fed research analyst application cycle has an explicit closed season.

2026-10-29: the employer's published Summer 2027 application window ended
September 14, and its 2027 internship applications are explicitly closed.
Empty results are legitimate *only while* that official notice remains present.
"""

import asyncio
from pathlib import Path

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS
from predoc_pipeline.core.health import source_status


CLOSED = "Applications for intern positions with a summer 2027 start date are now closed."


def source():
    return next(
        s for s in load_board_sources(Path("config/sources.toml"))
        if s.name == "ny_fed"
    )


class FixtureHttp:
    def __init__(self, html):
        self.html = html

    async def get_text(self, url):
        assert url == "https://www.newyorkfed.org/research/careers/research_analysts"
        return self.html


def scrape(html):
    cfg = source()
    return asyncio.run(
        _scrape_all([SCRAPERS[cfg.type](cfg, FixtureHttp(html))], 1, 5)
    )[0]


def test_closed_new_york_fed_hiring_window_is_known_empty_not_an_ingestion_failure():
    cfg = source()
    assert cfg.may_be_empty is True
    assert cfg.opt("verified_empty_marker") == CLOSED
    html = (
        "<h1>Research Analysts</h1>"
        "<p>Research Analyst | Summer 2027 | Aug. 24 – Sept. 14</p>"
        f"<p>{CLOSED}</p>"
    )
    result = scrape(html)
    assert result.ok
    assert result.posts == []
    assert result.as_stats()["errors"] == 0
    assert source_status(result.as_stats()) == "empty"


def test_changed_ny_fed_page_without_closed_notice_must_alert_not_silently_go_empty():
    result = scrape("<h1>Research Analysts</h1><p>New hiring cycle information</p>")
    assert result.posts == []
    assert result.ok is False
    assert result.as_stats()["failure_counts"]["parse"] == 1
    assert source_status(result.as_stats()) == "failed"


def test_future_real_ny_fed_application_link_is_collected_even_without_closed_marker():
    href = (
        "https://recruiting.wd1.myworkdayjobs.com/FRS/job/New-York/"
        "Research-Analyst_R0000000"
    )
    html = f'<a href="{href}">Research Analyst – Economics Research</a>'
    result = scrape(html)
    assert result.ok
    assert [post.url for post in result.posts] == [href]
    assert source_status(result.as_stats()) == "successful"
