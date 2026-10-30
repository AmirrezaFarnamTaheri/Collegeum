"""IFAU currently has an explicit, official empty recruitment state.

Unrelated archived postdocs and institute publication pages must not
create fake current research-assistant positions.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper


def source():
    return next(
        s for s in load_board_sources(Path("config/sources.toml"))
        if s.name == "ifau_sweden_labour"
    )


class Http:
    async def get_text(self, _url):
        return "We don't have any open positions at the moment"

    def set_host_interval(self, *_args):
        pass


def test_ifau_reuses_existing_source_and_an_explicit_empty_notice():
    cfg = source()
    assert cfg.enabled
    assert cfg.country == "Sweden"
    assert cfg.field_implied is False
    assert cfg.opt("may_be_empty")
    assert cfg.opt("verified_empty_reject_job_links")
    assert cfg.opt("verified_empty_marker") == (
        "We don't have any open positions at the moment"
    )
    assert cfg.opt("link_pattern").startswith("^https://")
    assert cfg.opt("url") == "https://www.ifau.se/en/About-IFAU/available-positions/"


def test_ifau_verified_notice_is_healthy_empty_only_when_observed():
    cfg = source()
    spider = LinkScanScraper(cfg, Http())
    jobs = spider.parse_postings([(
        cfg.opt("url"),
        "<main><h1>Available positions</h1>"
        "<p>We don't have any open positions at the moment, "
        "but please check back here for future opportunities.</p></main>",
    )])
    assert jobs == []
    assert spider.discovery_parse_errors == []
    assert spider.verified_empty_evidence is True


def test_ifau_missing_empty_notice_is_not_false_healthy():
    cfg = source()
    spider = LinkScanScraper(cfg, Http())
    posts = spider.parse_postings([(cfg.opt("url"), "<main>JavaScript recruitment shell</main>")])
    assert posts == []
    assert spider.discovery_parse_errors
    assert not spider.verified_empty_evidence


def test_ifau_archive_postdoc_cannot_become_current_vacancy():
    cfg = source()
    scraper = LinkScanScraper(cfg, Http())
    posts, _ = asyncio.run(scraper.run())
    assert not posts
    wrong = (
        '<article><a href="https://www.ifau.se/en/About-IFAU/tillsatta-tjanster/'
        'postdoctoral-position-in-economics-of-education/">'
        'Postdoctoral Position in Economics of Education</a></article>'
    )
    assert scraper.parse_postings([(cfg.opt("url"), wrong)]) == []
