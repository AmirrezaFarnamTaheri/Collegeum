"""UZH department index includes German and English employer job identities."""
from __future__ import annotations

import asyncio
from pathlib import Path

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS

INDEX = "https://www.econ.uzh.ch/en/about/jobs.html"
ENGLISH = (
    "https://jobs.uzh.ch/job-vacancies/"
    "pre-doctoral-program-global-talent-common-application/"
    "de0df20a-d294-46c1-8e4a-77db716745dc"
)
GERMAN = (
    "https://jobs.uzh.ch/offene-stellen/"
    "uebungsleiter-innen-gesucht-im-fs27-statistik/"
    "5a00f94f-a464-4059-bb12-3a96c4a5019d"
)


class Page:
    async def get_text(self, url: str) -> str:
        assert url == INDEX
        return (
            '<a href="' + ENGLISH +
            '">Pre-Doctoral Program - Global Talent Common Application</a>'
            '<a href="' + GERMAN +
            '">Uebungsleiter*innen gesucht im FS27 Statistik 10 - 20 %</a>'
            '<a href="https://jobs.uzh.ch.evil.example/offene-stellen/'
            'fake/12345">Fraudulent research assistant position</a>'
        )


def test_uzh_accepts_two_official_language_routes_but_no_lookalike() -> None:
    cfg = next(s for s in load_board_sources(Path("config/sources.toml"))
               if s.name == "uzh")
    assert cfg.opt("url") == INDEX
    result = asyncio.run(_scrape_all([SCRAPERS[cfg.type](cfg, Page())], 1, 5))[0]
    assert result.ok
    assert {post.url for post in result.posts} == {ENGLISH, GERMAN}


def test_uzh_discovery_does_not_label_tutoring_a_verified_economics_predoc() -> None:
    cfg = next(s for s in load_board_sources(Path("config/sources.toml"))
               if s.name == "uzh")
    result = asyncio.run(_scrape_all([SCRAPERS[cfg.type](cfg, Page())], 1, 5))[0]
    german = next(post for post in result.posts if post.url == GERMAN)
    # Discovery is only a raw candidate. The downstream eligibility gate
    # still decides whether this role is a predoc/research position.
    assert "Uebungsleiter" in german.title
    assert german.url.startswith("https://jobs.uzh.ch/offene-stellen/")
