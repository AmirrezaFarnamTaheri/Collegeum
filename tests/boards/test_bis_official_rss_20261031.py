"""BIS official RSS recovery and multi-country provenance, observed 31 Oct 2026.

Read-only runner #41209904409 found 7 distinct live BIS jobs in official
RSS 1.0 and 0 HTML-parser links in one normal HTTP-200 response.
Runner #41209998706 also checked a bounded paging_length=50 request.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers.rss import RSSScraper

CATALOGUE = Path(__file__).resolve().parents[2] / "config/sources.toml"
OFFICIAL_RSS = (
    "https://www.bis.org/doclist/vacancies.rss"
    "?objid=vacancies&page=&paging_length=50&sort_list=date_desc"
    "&theme=simple&ml=false&mlurl="
    "&emptylisttext=There%20are%20currently%20no%20vacancies."
)


class FakeHttp:
    def __init__(self, xml: str) -> None:
        self.xml = xml
        self.calls: list[str] = []

    def set_host_interval(self, *_args) -> None:
        pass

    async def get_text(self, url: str, **_kwargs) -> str:
        self.calls.append(url)
        return self.xml


def source():
    return next(s for s in load_board_sources(CATALOGUE) if s.name == "bis")


def _feed() -> str:
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        "<title>BIS current vacancies</title>"
        "<item><title>Data Scientist / Research Analyst</title>"
        "<link>https://www.bis.org/vacancy/jr100491</link>"
        "<description>The Bank is headquartered in Basel, Switzerland; "
        "this role is based in Hong Kong SAR. Economic and financial markets research."
        "</description></item>"
        "<item><title>Research Assistant in Monetary Economics</title>"
        "<link>https://www.bis.org/vacancy/jr100519</link>"
        "<description>This role is based in Basel, Switzerland. "
        "Monetary policy and financial stability research.</description></item>"
        "<item><title>Impersonated BIS Vacancy</title>"
        "<link>https://www.bis.org.attacker.invalid/vacancy/jr100520</link>"
        "<description>This role is based in Basel, Switzerland.</description></item>"
        "</channel></rss>"
    )


def test_bis_uses_official_rss_with_no_institutional_country_guess():
    cfg = source()
    assert cfg.enabled is True
    assert cfg.type == "rss"
    assert cfg.group == "central_bank"
    assert cfg.opt("url") == OFFICIAL_RSS
    assert cfg.country is None  # BIS also recruits in Hong Kong.
    assert cfg.opt("allowed_link_hosts") == ["bis.org", "www.bis.org"]
    assert cfg.opt("infer_country_from_summary") is True
    assert cfg.institution == "Bank for International Settlements"


def test_bis_official_requisitions_preserve_job_level_country_and_reject_spoofs():
    http = FakeHttp(_feed())
    scraper = RSSScraper(source(), http)
    rows, raw_count = asyncio.run(scraper.run())
    assert raw_count == 2
    assert len(rows) == 2
    assert http.calls == [OFFICIAL_RSS]
    by_id = {post.url.rsplit("/", 1)[-1]: post for post in rows}
    assert set(by_id) == {"jr100491", "jr100519"}
    assert by_id["jr100491"].country == "Hong Kong"
    assert "Hong Kong" in (by_id["jr100491"].location or "")
    assert by_id["jr100519"].country == "Switzerland"
    assert "Basel" in (by_id["jr100519"].location or "")
    assert by_id["jr100491"].source == "bis"
    assert by_id["jr100491"].field_implied is True
    assert scraper.discovery_parse_errors == [
        "feed entry link host is not a trusted source hostname"
    ]


def test_bis_unknown_workplace_is_not_inferred_from_employer_headquarters():
    xml = (
        '<rss version="2.0"><channel><item>'
        "<title>Data Scientist / Research Analyst</title>"
        "<link>https://bis.org/vacancy/jr100999</link>"
        "<description>The BIS has headquarters in Basel, Switzerland. "
        "The position location is not stated in this advert.</description>"
        "</item></channel></rss>"
    )
    scraper = RSSScraper(source(), FakeHttp(xml))
    posts, count = asyncio.run(scraper.run())
    assert count == 1
    assert posts[0].country is None
    assert posts[0].location is None


def test_unrelated_rss_sources_do_not_guess_country_from_description():
    from predoc_pipeline.boards.config import SourceConfig

    cfg = SourceConfig(name="other", type="rss", url="https://feed.example.org/jobs")
    scraper = RSSScraper(cfg, FakeHttp(_feed()))
    posts, _ = asyncio.run(scraper.run())
    assert posts[0].country is None
    assert posts[0].location is None
