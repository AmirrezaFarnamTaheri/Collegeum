"""Official VIB Jobsoid link drift and Life Sciences export country preservation."""
from __future__ import annotations

import asyncio
import csv
from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.boards.scrapers import SCRAPERS
from predoc_pipeline.ingest import life_sciences
from tools.export_life_sciences import collect


class HtmlClient:
    def __init__(self, url: str, html: str):
        self.url, self.html = url, html

    async def get_text(self, url: str) -> str:
        assert url == self.url
        return self.html


def test_vib_recognizes_current_employer_jobsoid_detail_urls():
    cfg = next(
        s for s in load_board_sources(Path("config/life_sciences.toml"))
        if s.name == "life_vib"
    )
    assert cfg.opt("url") == "https://jobs.vib.be/jobs"
    html = """
    <article class="job-card">
      <a href="/PortalJob/IntegratedJobDetails?dept=0&amp;div=0&amp;fun=0&amp;group=3&amp;id=138253&amp;loc=0&amp;slug=phd-position-in-neuroimmunology&amp;source=website">
        PhD Position in Neuroimmunology
      </a>
      <span>VIB-UAntwerp Center for Molecular Neurology</span>
    </article>
    <a href="/jobs?group=3">All vacancies</a>
    <a href="/apply/138253">Apply</a>
    """
    scraper = SCRAPERS[cfg.type](cfg, HtmlClient(cfg.opt("url"), html))
    posts, count = asyncio.run(scraper.run())
    assert count == 1
    assert len(posts) == 1
    assert posts[0].title == "PhD Position in Neuroimmunology"
    assert "id=138253" in posts[0].url
    assert posts[0].source == "life_vib"
    assert posts[0].country == "Belgium"
    assert scraper.discovery_parse_errors == []


def test_export_keeps_country_confirmed_from_vacancy_description(tmp_path, monkeypatch):
    config = tmp_path / "life_sciences.toml"
    config.write_text(
        '[[board]]\nname="life_description_location"\ntype="link_scan"\n'
        'url="https://example.org/jobs"\nlink_pattern="example.org/job/"\n',
        encoding="utf-8",
    )
    vacancy = JobPostSchema(
        title="PhD Position in Epigenetics",
        source="life_description_location",
        url="https://example.org/job/100",
        institution="Example Research Institute",
        country=None,
        location=None,
        description_snippet="Workplace: Berlin, Germany; epigenetics and chromatin biology",
    )
    expected = life_sciences.classify_post(vacancy)
    assert expected is not None and expected["country"] == "Germany"

    async def discover(_sources, _http, *, selected_names):
        assert selected_names == {"life_description_location"}
        return [vacancy], []

    monkeypatch.setattr(life_sciences, "discover", discover)
    positions = []
    report = {"collected_at": "2026-10-31T09:00:00+00:00", "batches": []}
    output = tmp_path / "life.csv"
    asyncio.run(collect(config, positions, output, report))

    assert len(positions) == 1
    assert positions[0]["country"] == "Germany"
    with output.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["country"] == "Germany"
