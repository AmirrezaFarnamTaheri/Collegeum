"""Yale's shared vacancy-index wrapper must not supply another job's hints."""
from pathlib import Path

from bs4 import BeautifulSoup

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS
from predoc_pipeline.boards.scrapers.link_scan import find_card

INDEX = "https://egc.yale.edu/opportunities/jobs-research-fellowships"
FELLOW = (
    "https://egc.yale.edu/opportunities/"
    "development-and-experimental-economics-research-fellow-1"
)
HTML = """
<div class="job-listings">
  <h3><a href="/opportunities/communications-associate">Communications Associate</a></h3>
  <p>Manage the website and social media. Deadline: 1 December 2026.</p>
  <h3><a href="/opportunities/development-and-experimental-economics-research-fellow-1">Development and Experimental Economics Research Fellow</a></h3>
  <p>Predoctoral quantitative research with a bachelor's or master's degree.</p>
</div>
"""


def test_yale_title_only_discovery_isolates_shared_wrapper():
    cfg = next(s for s in load_board_sources(Path("config/sources.toml"))
               if s.name == "yale_egc_jobs")
    scraper = SCRAPERS[cfg.type](cfg, object())
    posts = scraper.parse_postings([(INDEX, HTML)])
    fellow = next(p for p in posts if p.url == FELLOW)
    assert fellow.title == "Development and Experimental Economics Research Fellow"
    assert fellow.department is None
    assert fellow.deadline is None
    assert fellow.description_snippet == ""
    assert not fellow.field_implied


def test_title_only_card_guard_preserves_legacy_default():
    anchor = BeautifulSoup(HTML, "lxml").find_all("a")[1]
    # The old heuristic takes the shared wrapper, not a single vacancy.
    assert "Communications Associate" in find_card(anchor).get_text(" ", strip=True)
    assert find_card(anchor, title_only=True) is anchor
    assert "Communications Associate" not in find_card(
        anchor, title_only=True
    ).get_text(" ", strip=True)
    other = BeautifulSoup(
        '<article><a href="/job">Research assistant</a><p>Deadline: 1 December</p></article>',
        "lxml",
    ).a
    assert "Deadline" in find_card(other).get_text(" ", strip=True)
