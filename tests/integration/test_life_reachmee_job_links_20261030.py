"""ReachMee listings are the public, robots-accessible source behind two universities.

The university landing shells expose no job anchors, whereas the signed
ReachMee English public listings returned 22/16 job links in read-only probes.
"""
import asyncio
import re
from pathlib import Path

import pytest

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper

LIU = (
    "https://web103.reachmee.com/ext/I011/853/job"
    "?site=7&lang=UK&validator=d7a66c13be778ef950c393a904293789&job_id=29874"
)
SLU = (
    "https://web103.reachmee.com/ext/I017/1114/job"
    "?site=7&lang=UK&validator=87e4b706891e51f731ed44be28da8352&job_id=15980"
)


def source(name):
    config = Path("config/life_sciences_sources/nordics.toml")
    return next(x for x in load_board_sources(config) if x.name == name)


@pytest.mark.parametrize(
    "name,expected,other",
    [
        ("life_nordic_linkoping", LIU, SLU),
        ("life_nordic_slu", SLU, LIU),
    ],
)
def test_official_reachmee_listing_has_strict_institution_specific_job_ids(
    name, expected, other,
):
    cfg = source(name)
    assert cfg.enabled and cfg.type == "link_scan"
    assert not cfg.field_implied
    assert cfg.opt("url").startswith("https://web103.reachmee.com/ext/")
    assert cfg.opt("url").find("site=7") >= 0
    rx = re.compile(cfg.opt("link_pattern"), re.I)
    assert rx.search(expected)
    assert not rx.search(other)
    assert not rx.search("https://web103.reachmee.com/ext/I011/853/subscribe?site=7")
    assert not rx.search("https://liu.se/en/research/doctoral-studies")


class StubHttp:
    def __init__(self, html):
        self.html = html

    async def get_text(self, url):
        assert "https://web103.reachmee.com/ext/" in url
        return self.html

    def set_host_interval(self, url, delay):
        assert delay >= 0


@pytest.mark.parametrize(
    "name,url,other,title",
    [
        ("life_nordic_linkoping", LIU, SLU,
         "PhD student in Medical Science, AI and Bioinformatics"),
        ("life_nordic_slu", SLU, LIU,
         "PhD student in forest pathology: biotic risks to birch"),
    ],
)
def test_public_university_reachmee_job_anchor_preserves_identity_and_origin(
    name, url, other, title,
):
    cfg = source(name)
    html = (
        f'<a href="{url}">{title}</a>'
        f'<a href="{other}">Unrelated university doctoral post</a>'
        '<a href="/ext/I011/853/subscribe?site=7">Subscribe</a>'
    )
    rows, _ = asyncio.run(LinkScanScraper(cfg, StubHttp(html)).run())
    assert len(rows) == 1
    assert rows[0].title == title
    assert rows[0].url == url
    assert rows[0].country == "Sweden"
    assert not rows[0].field_implied
