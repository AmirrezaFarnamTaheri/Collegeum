"""BIS official RSS discovery must not silently become an empty HTML scrape.

Official read-only runner #41209904409 saw seven valid employer RSS 1.0
entries and zero links from the current HTML link_scan adapter.  The
employer recruits in Basel and Hong Kong, so do not assign a country to
all jobs before reading their own location evidence.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers.rss import RSSScraper

CONFIG = Path("config/sources.toml")
BASE = "https://www.bis.org/about/careers/vacancies"
HONG_KONG = "https://www.bis.org/vacancy/jr100491"
BASEL = "https://www.bis.org/vacancy/jr100516"


def _source():
    return next(s for s in load_board_sources(CONFIG) if s.name == "bis")


class Http:
    def __init__(self, feed: str):
        self.feed = feed

    async def get_text(self, _url: str, **_kwargs: object) -> str:
        return self.feed

    def set_host_interval(self, *_args: object) -> None:
        pass


def _feed() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
        ' xmlns="http://purl.org/rss/1.0/">'
        '<channel rdf:about="https://www.bis.org/doclist/vacancies.rss">'
        '<title>BIS current vacancies</title>'
        f'<link>{BASE}</link>'
        '<description>Bank for International Settlements</description>'
        '</channel>'
        f'<item rdf:about="{HONG_KONG}">'
        '<title>Data Scientist / Research Analyst</title>'
        f'<link>{HONG_KONG}</link>'
        '<description>Hong Kong position in economics and research.</description>'
        '</item>'
        f'<item rdf:about="{BASEL}">'
        '<title>2027 PhD Fellowship Programme</title>'
        f'<link>{BASEL}</link>'
        '<description>Basel, Switzerland fellowship.</description>'
        '</item>'
        '</rdf:RDF>'
    )


def test_bis_uses_verified_employer_rss_instead_of_html_zero():
    source = _source()
    assert source.enabled
    assert source.type == "rss"
    assert source.opt("url").startswith("https://www.bis.org/doclist/vacancies.rss?")
    assert source.opt("allowed_link_hosts") == ["www.bis.org", "bis.org"]
    assert source.field_implied is True
    assert not source.may_be_empty


def test_bis_cannot_assign_swiss_country_to_multicountry_recruitment():
    source = _source()
    assert source.country is None
    scraper = RSSScraper(source, Http(_feed()))
    jobs, count = asyncio.run(scraper.run())
    assert count == 2
    assert {x.url for x in jobs} == {HONG_KONG, BASEL}
    assert all(x.source == "bis" for x in jobs)
    assert all(x.country is None for x in jobs)
    assert all("source_country_default" not in x.extra for x in jobs)
    assert scraper.discovery_parse_errors == []


def test_bis_rss_rejects_spoofed_employer_hostname():
    feed = _feed().replace(
        HONG_KONG,
        "https://www.bis.org.attacker.invalid/vacancy/jr100491",
    )
    scraper = RSSScraper(_source(), Http(feed))
    jobs, count = asyncio.run(scraper.run())
    assert count == 1
    assert [x.url for x in jobs] == [BASEL]
    assert scraper.discovery_parse_errors == [
        "feed entry link host is not a trusted source hostname"
    ]
