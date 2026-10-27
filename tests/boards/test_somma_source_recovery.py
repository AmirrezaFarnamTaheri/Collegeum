"""Regression: SOMMa posts real job titles in table cells, not in 'More info' links."""

import asyncio
from datetime import date
from pathlib import Path

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS


class FixtureHttp:
    def __init__(self, url: str, html: str):
        self.url, self.html = url, html
        self.requests: list[str] = []

    async def get_text(self, url: str) -> str:
        self.requests.append(url)
        assert url == self.url
        return self.html


def source():
    return next(
        s for s in load_board_sources(Path("config/sources.toml"))
        if s.name == "somma"
    )


def test_somma_recovers_live_cemfi_predoc_from_job_table_and_metadata():
    cfg = source()
    html = """
    <nav><a href="https://somma.es/jobs/">Jobs</a></nav>
    <table><thead><tr><th>Job Title</th><th>Category</th><th>Institution</th>
        <th>Location</th><th>Deadline</th><th>Info</th></tr></thead>
    <tbody>
      <tr><td class="title">2026-I RESEARCH ASSISTANT PRE-DOC</td>
        <td class="job_category">Research Support</td>
        <td class="institution">Centre for Monetary and Financial Studies (CEMFI)</td>
        <td class="province">Madrid</td>
        <td class="deadline">October 31, 2026</td>
        <td class="actions"><a href="https://somma.es/job/2026-i-research-assistant-pre-doc/">More info</a></td></tr>
      <tr><td class="title">Postdoctoral Researcher – Health Economics</td>
        <td class="job_category">Postdoc</td>
        <td class="institution">Institute for Global Health</td>
        <td class="province">Barcelona</td>
        <td class="deadline">November 12, 2026</td>
        <td class="actions"><a href="https://somma.es/job/postdoctoral-researcher-health-economics/">More info</a></td></tr>
    </tbody></table>
    <footer><a href="/job/">More info</a></footer>
    """
    http = FixtureHttp(cfg.opt("url"), html)
    result = asyncio.run(_scrape_all([SCRAPERS[cfg.type](cfg, http)], 1, 5))[0]
    assert result.ok and result.as_stats()["errors"] == 0
    assert len(result.posts) == 2
    predoc = result.posts[0]
    assert predoc.title == "2026-I RESEARCH ASSISTANT PRE-DOC"
    assert predoc.url == "https://somma.es/job/2026-i-research-assistant-pre-doc"
    assert predoc.institution == "Centre for Monetary and Financial Studies (CEMFI)"
    assert predoc.location == "Madrid"
    assert predoc.country == "Spain"
    assert predoc.deadline == date(2026, 10, 31)
    assert result.posts[1].title.startswith("Postdoctoral Researcher")
    assert result.posts[1].deadline == date(2026, 11, 12)
    assert http.requests == [cfg.opt("url")]


def test_somma_does_not_invent_job_from_navigation_or_generic_more_info_link():
    cfg = source()
    url = cfg.opt("url")
    html = """
    <nav><a href="/job/">More info</a></nav>
    <table><thead><tr><th>Job Title</th></tr></thead><tbody>
      <tr><td class="title">No current jobs</td><td class="actions">
        <a href="https://example.invalid/job/external">More info</a></td></tr>
    </tbody></table>
    """
    result = asyncio.run(_scrape_all([
        SCRAPERS[cfg.type](cfg, FixtureHttp(url, html))
    ], 1, 5))[0]
    assert result.posts == []
