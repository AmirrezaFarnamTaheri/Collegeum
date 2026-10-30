"""DKFZ official recruitment recovery with strict closing-date evidence."""
from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper
from predoc_pipeline.ingest import life_sciences

CONFIG = Path("config/life_sciences.toml")
EXPIRED = "https://jobs.dkfz.de/en/jobs/168859/phd-position-in-computational-biologybioinformatics"
POSTDOC = "https://jobs.dkfz.de/en/jobs/168914/postdoc-position-in-preclinical-development"
MANAGEMENT = "https://jobs.dkfz.de/en/jobs/168899/division-head-in-cancer-early-detection-imaging"


class Http:
    def __init__(self, html: str = "") -> None:
        self.html = html

    async def get_text(self, _url: str) -> str:
        return self.html

    def set_host_interval(self, _url: str, _delay: float) -> None:
        pass


def get_source():
    return next(cfg for cfg in load_board_sources(CONFIG) if cfg.name == "life_dkfz")


def test_dkfz_is_one_existing_real_job_index_not_an_extra_candidate():
    source = get_source()
    assert not source.enabled
    assert source.type == "link_scan"
    assert source.country == "Germany"
    assert source.opt("url") == "https://jobs.dkfz.de/en/jobs"
    assert source.opt("require_deadline") is True
    assert source.field_implied is False
    assert source.opt("title_allow_pattern")


def test_dkfz_index_accepts_doctoral_roles_only_and_propagates_deadline_gate():
    html = (
        f'<a href="{EXPIRED}">PhD Position in Computational Biology/Bioinformatics</a>'
        f'<a href="{POSTDOC}">Postdoc Position in Preclinical Development</a>'
        f'<a href="{MANAGEMENT}">Division Head in Cancer Early Detection Imaging</a>'
    )
    # The narrow title filter is applied by BaseScraper.run(), not parse_postings.
    scraper = LinkScanScraper(get_source(), Http(html))
    posts, _ = asyncio.run(scraper.run())
    assert [job.url for job in posts] == [EXPIRED]
    assert posts[0].extra["require_deadline"] is True
    assert life_sciences._needs_detail(posts[0])
    assert life_sciences.classify_post(posts[0], today=date(2026, 10, 30)) is None

    posts[0].deadline = date(2026, 10, 29)
    assert life_sciences.classify_post(posts[0], today=date(2026, 10, 30)) is None
    posts[0].deadline = date(2026, 11, 30)
    assert life_sciences.classify_post(posts[0], today=date(2026, 10, 30)) is not None
