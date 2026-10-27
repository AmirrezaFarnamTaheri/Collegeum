"""Regression checks for 2026 European Job Market and ifo source changes."""
from __future__ import annotations

import asyncio
from pathlib import Path

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS


def _production(name: str):
    registry = Path("config/sources.toml")
    return next(s for s in load_board_sources(registry) if s.name == name)


class FixtureHttp:
    def __init__(self, url: str, html: str):
        self.url = url
        self.html = html
        self.requests: list[str] = []

    async def get_text(self, url: str) -> str:
        self.requests.append(url)
        if url == self.url:
            return self.html
        if url.startswith(self.url + "?page="):
            return "<p>No additional listings</p>"
        raise RuntimeError("unexpected or obsolete endpoint")


def test_ejm_upstream_template_links_are_skipped_not_reported_as_parser_failures():
    """The live EJM page contains literal [nid] placeholders, not job IDs."""
    config = _production("european_job_market")
    markup = (
        '<article class="views-row">'
        '<h3>Postdoctoral Researcher in Political Economy</h3>'
        '<a href="/job-listing/postdoctoral-researcher-in-political-economy/%5Bnid%5D">'
        'Read more</a></article>'
    )
    transport = FixtureHttp("https://www.europeanjobmarketofeconomists.org/job-listings", markup)
    scraper = SCRAPERS[config.type](config, transport)
    result = asyncio.run(_scrape_all([scraper], 1, 5))[0]
    status = result.as_stats()
    assert status["skipped"] is True
    assert status["items"] == 0
    assert status["errors"] == 0
    assert "unresolved" in status["messages"][0].lower()


def test_ejm_recovers_automatically_when_upstream_publishes_real_ids():
    config = _production("european_job_market")
    markup = (
        '<article class="views-row">'
        '<h3><a href="/job-listing/research-assistant-in-economics/81203">'
        'Research Assistant in Economics</a></h3></article>'
    )
    transport = FixtureHttp("https://www.europeanjobmarketofeconomists.org/job-listings", markup)
    result = asyncio.run(_scrape_all([SCRAPERS[config.type](config, transport)], 1, 5))[0]
    assert result.ok and not result.skipped
    assert len(result.posts) == 1
    assert result.posts[0].url.endswith("/81203")
    assert result.posts[0].title == "Research Assistant in Economics"
    assert transport.requests == [
        transport.url, transport.url + "?page=1",
    ]


def test_ifo_scrapes_current_careers_page_and_uses_job_titles_not_link_labels():
    config = _production("ifo")
    html = (
        '<div class="views-row">'
        '<h5>Research Economist (w/m/d) in Education</h5>'
        '<a href="/stellenangebot/research-economist-education">Mehr erfahren</a>'
        '</div>'
        '<article class="teaser">'
        '<h5>Postdoctoral Researcher (f/m/d)</h5>'
        '<a href="/stellenangebot-/2026-10-10/postdoctoral-researcher">Stellenangebot</a>'
        '</article>'
        '<footer><a href="/karriere-am-ifo">Karriere am ifo</a></footer>'
    )
    transport = FixtureHttp("https://www.ifo.de/karriere-am-ifo", html)
    result = asyncio.run(_scrape_all([SCRAPERS[config.type](config, transport)], 1, 5))[0]
    assert result.ok and result.as_stats()["errors"] == 0
    assert transport.requests == ["https://www.ifo.de/karriere-am-ifo"]
    assert len(result.posts) == 2
    assert {p.title for p in result.posts} == {
        "Research Economist (w/m/d) in Education", "Postdoctoral Researcher (f/m/d)",
    }
    assert all("stellenangebot" in p.url for p in result.posts)


def test_ifo_live_qz_link_custom_element_recovers_postdoc_advert():
    """ifo's October 2026 page puts real vacancy URLs in <qz-link>, not <a>."""
    config = _production("ifo")
    html = """
    <section>
      <div class="bg-theme-primary-fg py-sm px-6 text-base mb-sm flex w-full gap-sm">
        <div class="w-54 flex flex-col"><qz-tag size="small">
          <a href="/karriere-am-ifo">Stellenangebot</a>
        </qz-tag></div>
        <div class="w-full">
          <h5><span>Postdoctoral Researcher (f/m/d) for the ifo Center for
          International Economics</span></h5>
          <div class="field field--text"><p>
            We seek a Postdoctoral Researcher (f/m/d) focused on international economics.
          </p></div>
          <qz-link
             href="/stellenangebot-deprecated/postdoctoral-researcher-fmd-ifo-center-international-economics"
             aria-label="Postdoctoral Researcher (f/m/d) for the ifo Center for International Economics"
             title="Postdoctoral Researcher (f/m/d) for the ifo Center for International Economics"
             variant="news-card">Mehr erfahren <qz-icon name="arrow-right"></qz-icon></qz-link>
        </div>
      </div>
      <div class="bg-theme-primary-fg py-sm px-6 text-base mb-sm flex w-full gap-sm">
        <div class="w-full"><h5>Praktikant*innen (VWL, BWL)</h5>
          <qz-link href="/stellenangebot-deprecated/praktikantinnen"
                   title="Praktikant*innen (VWL, BWL)">Mehr erfahren</qz-link>
        </div>
      </div>
    </section>
    """
    transport = FixtureHttp("https://www.ifo.de/karriere-am-ifo", html)
    result = asyncio.run(_scrape_all([SCRAPERS[config.type](config, transport)], 1, 5))[0]
    assert result.ok
    assert result.as_stats()["errors"] == 0
    assert len(result.posts) == 2
    assert result.posts[0].title == (
        "Postdoctoral Researcher (f/m/d) for the ifo Center for International Economics"
    )
    assert result.posts[0].url == (
        "https://www.ifo.de/stellenangebot-deprecated/"
        "postdoctoral-researcher-fmd-ifo-center-international-economics"
    )
    assert "international economics" in result.posts[0].description_snippet.lower()
    assert transport.requests == ["https://www.ifo.de/karriere-am-ifo"]


def test_other_link_scan_sources_ignore_qz_links_by_default():
    """ifo's custom element must not silently change unrelated board discovery."""
    from predoc_pipeline.boards.config import SourceConfig
    from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper

    url = "https://example.org/jobs"
    scraper = LinkScanScraper(SourceConfig(
        name="unrelated", type="link_scan", url=url, link_pattern=r"/job/\\d+"
    ), FixtureHttp(url, ""))
    html = '<qz-link href="/job/123" title="Research Assistant">Learn more</qz-link>'
    assert scraper.parse_postings([(url, html)]) == []
