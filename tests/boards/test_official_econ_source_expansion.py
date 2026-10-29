"""Official-source expansion: real vacancy links, safe empty periods, no directory links."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS
from predoc_pipeline.core.health import source_status


SOURCES = {
    "yale_egc_jobs": "https://egc.yale.edu/opportunities/jobs-research-fellowships",
    "wharton_predoc": "https://upenn.wd1.myworkdayjobs.com/Wharton",
    "princeton_rpde_jobs": "https://rpde.princeton.edu/opportunities/jobs",
    "brookings_jobs": "https://careers-brookings.icims.com/jobs/search?hashed=-435682078&ss=1",
    "ucl_management_jobs": "https://www.mgmt.ucl.ac.uk/vacancies",
}


def source(name):
    return next(s for s in load_board_sources(Path("config/sources.toml")) if s.name == name)


class PageHttp:
    def __init__(self, url, html):
        self.url, self.html = url, html

    async def get_text(self, url):
        assert url == self.url
        return self.html


def scrape(name, html):
    cfg = source(name)
    return asyncio.run(_scrape_all(
        [SCRAPERS[cfg.type](cfg, PageHttp(cfg.opt("url"), html))], 1, 5
    ))[0]


@pytest.mark.parametrize(("name", "url"), list(SOURCES.items()))
def test_official_source_is_enabled_with_distinct_employer_url(name, url):
    sources = load_board_sources(Path("config/sources.toml"))
    cfg = source(name)
    assert cfg.enabled is True
    assert cfg.opt("url") == url
    assert cfg.may_be_empty is True
    assert cfg.field_implied is False
    assert sum(s.name == name for s in sources) == 1
    assert sum(s.opt("url") == url for s in sources) == 1


@pytest.mark.parametrize(("name", "job_url", "title", "page"), [
    (
        "yale_egc_jobs",
        "https://egc.yale.edu/opportunities/development-economics-research-fellow-2",
        "Development Economics Research Fellow",
        "Current job openings",
    ),
    (
        "princeton_rpde_jobs",
        "https://main-princeton.icims.com/jobs/4583/senior-research-specialist/job",
        "Senior Research Specialist",
        "Open Positions",
    ),
    (
        "brookings_jobs",
        "https://careers-brookings.icims.com/jobs/3923/research-assistant-economic-studies/job",
        "Research Assistant, Economic Studies",
        "Search Results Page 1 of 1",
    ),
    (
        "ucl_management_jobs",
        "https://www.mgmt.ucl.ac.uk/vacancies/research-assistant-finance-accounting-and-economics-0",
        "Research Assistant in Finance, Accounting and Economics",
        "Job vacancies",
    ),
])
def test_employer_source_collects_only_specific_job_detail_links(
    name, job_url, title, page
):
    cfg = source(name)
    assert re.search(cfg.opt("link_pattern"), job_url)
    html = (
        f"<h1>{page}</h1>"
        f'<a href="{job_url}">{title}</a>'
        '<a href="https://example.org/research/publications">Research publications</a>'
        '<a href="/about">About us</a>'
    )
    result = scrape(name, html)
    assert result.ok
    assert [post.url for post in result.posts] == [job_url]
    assert result.posts[0].field_implied is False
    assert source_status(result.as_stats()) == "successful"


@pytest.mark.parametrize(("name", "marker"), [
    ("yale_egc_jobs", "Current job openings"),
    ("princeton_rpde_jobs", "Open Positions"),
    ("brookings_jobs", "Search Results Page 1 of 1"),
    ("ucl_management_jobs", "Job vacancies"),
])
def test_official_no_open_jobs_is_valid_only_on_expected_page(name, marker):
    cfg = source(name)
    assert cfg.opt("verified_empty_marker") in marker
    result = scrape(name, f"<h1>{marker}</h1><p>No qualifying roles this cycle.</p>")
    assert result.ok
    assert result.posts == []
    assert source_status(result.as_stats()) == "empty"

    redirected = scrape(name, "<h1>Unrelated news article</h1>")
    assert not redirected.ok
    assert source_status(redirected.as_stats()) == "failed"


class WorkdayHttp:
    def __init__(self):
        self.requests = []

    async def post_json(self, url, data):
        self.requests.append((url, data))
        assert url == "https://upenn.wd1.myworkdayjobs.com/wday/cxs/upenn/Wharton/jobs"
        assert data["limit"] <= 20
        if data["searchText"] == "predoctoral":
            return {
                "total": 1,
                "jobPostings": [
                    {
                        "title": "Pre-Doctoral Research Specialist - Economics",
                        "externalPath": "/job/Dinan-Hall/Pre-Doctoral-Research-Specialist_JR00128503",
                        "locationsText": "Philadelphia, PA",
                        "postedOn": "Posted 2 Days Ago",
                    }
                ],
            }
        return {"total": 0, "jobPostings": []}


def test_wharton_uses_its_official_workday_api_with_real_requisition_identity():
    cfg = source("wharton_predoc")
    assert cfg.type == "workday"
    assert "predoctoral" in cfg.opt("search_terms")
    client = WorkdayHttp()
    result = asyncio.run(_scrape_all([SCRAPERS[cfg.type](cfg, client)], 1, 5))[0]
    assert result.ok
    assert [post.title for post in result.posts] == [
        "Pre-Doctoral Research Specialist - Economics"
    ]
    assert result.posts[0].url.endswith(
        "/Wharton/job/Dinan-Hall/Pre-Doctoral-Research-Specialist_JR00128503"
    )
    assert source_status(result.as_stats()) == "successful"
    assert all(post.field_implied is False for post in result.posts)
