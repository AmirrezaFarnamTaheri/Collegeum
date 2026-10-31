"""Life Sciences AcademicTransfer must parse empty overlay anchors like the working main feed."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper
from predoc_pipeline.ingest.life_sciences import classify_post, load_life_sources

CATALOG = Path("config/life_sciences.toml")
TOPICS = {
    "life_academictransfer",
    "life_academictransfer_epigenomics",
    "life_academictransfer_cell_models",
    "life_academictransfer_rna",
}


class NoFetchHttp:
    def set_host_interval(self, *_args):
        return None


# This is a reduced, synthetic fixture of the official 2026-10-31 card shape:
# each full-card <a> overlay is empty, with its title in a sibling <h3>.
HTML = """
<article class="job-card">
  <a href="/en/jobs/364486/phd-position-in-epigenetics/"></a>
  <h3>PhD Position in Epigenetics</h3>
  <div class="md:col-start-8">
    <span class="text-at-small text-gray-700">Leiden University</span>
  </div>
  <span class="text-at-small flex items-center gap-1 text-gray-500">
    Leiden, Netherlands
  </span>
</article>
<article class="job-card">
  <a href="/en/jobs/364487/phd-position-in-epigenetics-uk/"></a>
  <h3>PhD Position in Epigenetics</h3>
  <div class="md:col-start-8">
    <span class="text-at-small text-gray-700">University of Cambridge</span>
  </div>
  <span class="text-at-small flex items-center gap-1 text-gray-500">
    Cambridge, United Kingdom
  </span>
</article>
"""


def test_all_four_academictransfer_life_feeds_reuse_proven_card_selectors():
    sources = {
        source.name: source
        for source in load_life_sources(CATALOG)
        if source.name in TOPICS
    }
    assert set(sources) == TOPICS
    for source in sources.values():
        selectors = source.opt("selectors")
        assert selectors["item"] == "article"
        assert selectors["title"] == "h3"
        assert "a[href" in selectors["link"]
        assert selectors.get("location")
        assert source.country is None  # Portal spans employers in multiple countries.


def test_empty_anchor_overlay_still_yields_real_doctoral_job_and_location():
    source = next(
        s for s in load_life_sources(CATALOG) if s.name == "life_academictransfer"
    )
    parser = LinkScanScraper(source, NoFetchHttp())
    postings = parser.parse_postings([(source.urls()[0], HTML)])
    assert len(postings) == 2
    assert all(p.url.startswith("https://www.academictransfer.com/en/jobs/") for p in postings)
    assert postings[0].title == "PhD Position in Epigenetics"
    assert postings[0].institution == "Leiden University"
    assert postings[0].location.strip() == "Leiden, Netherlands"
    dutch = classify_post(postings[0], today=date(2026, 10, 31))
    assert dutch is not None
    assert dutch["country"] == "Netherlands"
    # UK roles may appear in the same aggregator; never treat them as Dutch.
    assert classify_post(postings[1], today=date(2026, 10, 31)) is None
