"""DKFZ official RSS discovery and evidence-based doctoral classification."""
from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers.rss import RSSScraper
from predoc_pipeline.ingest import life_sciences

CONFIG = Path("config/life_sciences.toml")
EXPIRED = "https://jobs.dkfz.de/en/jobs/168859/phd-position-in-computational-biologybioinformatics"
POSTDOC = "https://jobs.dkfz.de/en/jobs/168914/postdoc-position-in-preclinical-development"
MANAGEMENT = "https://jobs.dkfz.de/en/jobs/168899/division-head-in-cancer-early-detection-imaging"


class Http:
    def __init__(self, xml: str = "") -> None:
        self.xml = xml

    async def get_text(self, _url: str, **_kwargs: object) -> str:
        return self.xml

    def set_host_interval(self, _url: str, _delay: float) -> None:
        pass


def get_source():
    return next(cfg for cfg in load_board_sources(CONFIG) if cfg.name == "life_dkfz")


def _mixed_job_feed() -> str:
    entries = [
        (
            "PhD Position in Computational Biology/Bioinformatics",
            EXPIRED,
            "Doctoral research in computational biology and molecular biology.",
        ),
        (
            "Postdoc Position in Preclinical Development",
            POSTDOC,
            "A postdoctoral researcher with an existing PhD is required.",
        ),
        (
            "Division Head in Cancer Early Detection Imaging",
            MANAGEMENT,
            "Leadership role requiring extensive work experience.",
        ),
    ]
    items = "".join(
        f"<item><title>{title}</title><link>{url}</link>"
        f"<description>{description}</description></item>"
        for title, url, description in entries
    )
    return f'<rss version="2.0"><channel><title>DKFZ Jobs</title>{items}</channel></rss>'


def test_dkfz_is_one_enabled_official_rss_index_not_an_extra_candidate():
    source = get_source()
    assert source.enabled
    assert source.type == "rss"
    assert source.country == "Germany"
    assert source.opt("url") == "https://jobs.dkfz.de/en/jobs"
    assert source.opt("require_deadline") is True
    assert source.field_implied is False
    assert source.opt("rss_user_agent").startswith("Collegeum-")
    assert source.opt("allowed_link_hosts") == ["jobs.dkfz.de"]


def test_dkfz_rss_can_list_general_jobs_without_publishing_ineligible_roles():
    scraper = RSSScraper(get_source(), Http(_mixed_job_feed()))
    posts, count = asyncio.run(scraper.run())
    assert count == 3
    assert {post.url for post in posts} == {EXPIRED, POSTDOC, MANAGEMENT}

    by_url = {post.url: post for post in posts}
    phd = by_url[EXPIRED]
    assert phd.extra["require_deadline"] is True
    assert life_sciences._needs_detail(phd)
    assert life_sciences.classify_post(phd, today=date(2026, 10, 30)) is None

    phd.deadline = date(2026, 10, 29)
    assert life_sciences.classify_post(phd, today=date(2026, 10, 30)) is None
    phd.deadline = date(2026, 11, 30)
    accepted = life_sciences.classify_post(phd, today=date(2026, 10, 30))
    assert accepted is not None
    assert accepted["deadline"] == "2026-11-30"
    assert accepted["country"] == "Germany"
    for url in (POSTDOC, MANAGEMENT):
        assert life_sciences.classify_post(by_url[url], today=date(2026, 10, 30)) is None
