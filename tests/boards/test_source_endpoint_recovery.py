"""Source route regressions grounded in official vacancy landing pages (Oct 2026)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS


def source(name):
    return next(s for s in load_board_sources(Path("config/sources.toml")) if s.name == name)


@pytest.mark.parametrize(("name", "expected_url"), [
    ("carlo_alberto", "https://www.carloalberto.org/about/jobs-fellowships/"),
    ("eth_lawecon", "https://lawecon.ethz.ch/group/open-positions.html"),
    ("iies_stockholm", "https://www.su.se/english/divisions/institute-for-international-economic-studies/about-the-institute/work-with-us"),
    ("iwh_halle", "https://www.iwh-halle.de/en/career/jobs/jobs-at-iwh"),
    ("opportunity_insights", "https://opportunityinsights.org/joinourteam/"),
    ("bde_spain", "https://www.bde.es/wbe/es/sobre-banco/trabajar-banco/convocatorias-plazo-abierto/"),
])
def test_removed_source_endpoints_are_replaced_with_official_pages(name, expected_url):
    assert source(name).opt("url") == expected_url


class FixtureHttp:
    def __init__(self, url, html):
        self.url, self.html = url, html

    async def get_text(self, url):
        assert url == self.url
        return self.html


def test_carlo_alberto_discovers_open_roles_but_never_closed_history():
    cfg = source("carlo_alberto")
    html = """
    <h2>CURRENTLY OPEN</h2>
    <a href="/about/jobs-fellowships/research-assistantships/">Research Assistantships</a>
    <a href="/about/jobs-fellowships/post-doctoral-position-new/">Post-doctoral position</a>
    <h2>CURRENTLY CLOSED</h2>
    <a href="/about/jobs-fellowships/research-assistant-in-2024/">Research Assistant in 2024</a>
    """
    result = asyncio.run(_scrape_all(
        [SCRAPERS[cfg.type](cfg, FixtureHttp(cfg.opt("url"), html))], 1, 5,
    ))[0]
    assert result.ok
    assert len(result.posts) == 2
    assert all("2024" not in post.url for post in result.posts)


def test_carlo_alberto_missing_closed_marker_is_not_treated_as_valid_empty():
    cfg = source("carlo_alberto")
    html = '<h2>CURRENTLY OPEN</h2><a href="/about/jobs-fellowships/ra/">Research Assistant</a>'
    result = asyncio.run(_scrape_all(
        [SCRAPERS[cfg.type](cfg, FixtureHttp(cfg.opt("url"), html))], 1, 5,
    ))[0]
    assert not result.ok
    assert result.as_stats()["errors"] > 0


def test_spanish_central_bank_links_match_actual_open_vacancies():
    import re

    cfg = source("bde_spain")
    role = ("https://www.bde.es/wbe/es/sobre-banco/trabajar-banco/"
            "becas-investigacion-ayudas-bde/"
            "personal-investigador-en-temas-de-economia-y-finanzas2026.html")
    assert re.search(cfg.opt("link_pattern"), role)
    assert not re.search(cfg.opt("link_pattern"), "https://www.bde.es/wbe/es/noticias/")
