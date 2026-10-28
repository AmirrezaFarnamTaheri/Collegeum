"""ECB moved its official vacancies to talent.ecb.europa.eu in October 2026."""

import asyncio
from pathlib import Path

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS

CAREERS = "https://talent.ecb.europa.eu/careers"
SEARCH = CAREERS + "/SearchJobs"
ECON_ROLE = (
    CAREERS + "/JobDetail/PhD-Traineeship-in-the-Directorate-General-Economics-"
    "Supply-Side-Labour-and-Surveillance-Division/15381"
)
MONETARY_ROLE = (
    CAREERS + "/JobDetail/Traineeship-in-the-Monetary-Analysis-Division-in-the-"
    "Directorate-General-Monetary-Policy/15446"
)


class FixtureHttp:
    def __init__(self, html):
        self.html = html
        self.requested = []

    async def get_text(self, url):
        self.requested.append(url)
        assert url == SEARCH
        return self.html


def source():
    return next(
        s for s in load_board_sources(Path("config/sources.toml"))
        if s.name == "ecb"
    )


def test_ecb_official_url_replaces_non_resolving_legacy_host():
    cfg = source()
    assert cfg.type == "link_scan"
    assert cfg.opt("url") == SEARCH
    assert "jobs.ecb.europa.eu" not in cfg.opt("url")
    assert cfg.institution == "European Central Bank"


def test_ecb_parses_real_vacancy_cards_and_rejects_social_links():
    html = f"""
      <h1>Job Search | European Central Bank</h1>
      <article><h3><a href="{ECON_ROLE}">
        PhD Traineeship in the Directorate General Economics
      </a></h3><a href="{CAREERS}/ApplicationMethods?jobId=15381">Apply</a></article>
      <article><h3><a href="{MONETARY_ROLE}">
        Traineeship in the Monetary Analysis Division
      </a></h3></article>
      <a href="{ECON_ROLE}?source=facebook">Social share</a>
      <a href="{CAREERS}/SearchJobs">Search jobs</a>
      <a href="{CAREERS}/Login">Login</a>
      <a href="https://talent.ecb.europa.eu.evil.invalid/careers/JobDetail/Fake/123">
        Malicious hostname
      </a>
      <a href="https://evil.invalid/redirect?next={ECON_ROLE}">Redirect</a>
      <a href="https://talent.ecb.europa.eu/careers/JobDetail/Fake/">No ID</a>
    """
    client = FixtureHttp(html)
    cfg = source()
    result = asyncio.run(
        _scrape_all([SCRAPERS[cfg.type](cfg, client)], 1, 5)
    )[0]

    assert result.ok
    assert [p.url for p in result.posts] == [ECON_ROLE, MONETARY_ROLE]
    assert result.posts[0].title == (
        "PhD Traineeship in the Directorate General Economics"
    )
    assert result.posts[0].institution == "European Central Bank"
    assert result.posts[0].country == "Germany"
    assert client.requested == [SEARCH]


def test_ecb_blank_portal_or_login_shell_is_source_failure_not_benign_empty():
    cfg = source()
    html = '<h1>Job Search</h1><a href="/careers/Login">Login</a>'
    result = asyncio.run(
        _scrape_all([SCRAPERS[cfg.type](cfg, FixtureHttp(html))], 1, 5)
    )[0]
    assert not result.ok
    assert result.posts == []
    assert result.as_stats()["failure_counts"]["parse"] > 0
