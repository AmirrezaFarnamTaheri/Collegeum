"""Preferences apply to every listing, whichever source or extractor produced it."""

import pytest

from predoc_pipeline.boards.config import load_preferences
from predoc_pipeline.core import gating
from predoc_pipeline.extract.heuristic import UNKNOWN_INSTITUTION, HeuristicExtractor
from predoc_pipeline.models import Location, PredocListing, RawItem, coerce
from predoc_pipeline.policy import Policy
from tests.boards.conftest import ROOT

PREFS = load_preferences(ROOT / "config" / "preferences.toml")
POLICY = Policy(PREFS)
EXTRACTOR = HeuristicExtractor(PREFS)


def feed_item(title: str, text: str, url: str = "https://jobs.example.org/1") -> RawItem:
    return RawItem(source="feed:test", source_url=url, title=title, text=text)


def verdict(item: RawItem) -> str | None:
    """Gate -> heuristic extraction -> coerce -> preferences, as the pipeline does."""
    gate = gating.evaluate(item.text, title=item.title, url=item.source_url)
    if not gate.passed:
        return f"gate:{gate.reason}"
    result = EXTRACTOR.extract(text=item.text, source_url=item.source_url, title=item.title)
    if not result.is_vacancy:
        return f"extract:{result.rejection_reason}"
    return POLICY.check(coerce(result, source_url=item.source_url), item)


def test_good_european_predoc_passes_and_is_parsed():
    item = feed_item(
        "Predoctoral Research Assistant in Economics",
        "The Department of Economics at the University of Oslo, Norway, invites applications "
        "for a predoctoral research assistant. You will work with Professor Kari Nordmann on "
        "labour economics. Visa sponsorship is available. Application deadline: 1 December 2026.",
    )
    assert verdict(item) is None
    result = EXTRACTOR.extract(text=item.text, source_url=item.source_url, title=item.title)
    assert "University of Oslo" in result.institution
    assert result.country == "Norway"
    assert result.deadline.startswith("2026-12-01")
    assert result.visa_sponsorship_status == "explicit"
    assert result.principal_investigator == "Kari Nordmann"
    assert "Labor Economics" in result.disciplines


@pytest.mark.parametrize("title,text,reason", [
    ("Predoctoral Research Associate - Economics",
     "J-PAL Europe is hiring a predoctoral research associate in economics. Apply by 1 Dec 2026.",
     "excluded-employer"),
    ("Pre-doctoral Research Assistant in Economics",
     "Stanford University is hiring a predoctoral research assistant in economics in Stanford, "
     "California. Applications are invited until 1 December 2026.",
     "region-US"),
    ("Research Assistant in Developmental Psychology",
     "The University of Oslo is hiring a research assistant in developmental psychology. "
     "Applications are invited until 1 December 2026.",
     "wrong-field"),
    ("Research Assistant, Equity Research",
     "Canaccord Genuity is hiring a research assistant for equity research on metals and "
     "mining. Apply by 1 December 2026.",
     "excluded-title"),
    ("Predoctoral Research Assistant in Economics",
     "The University of Oslo is hiring a predoctoral research assistant in economics. "
     "Applications are invited. Update: this position has been filled.",
     "filled-or-closed"),
    ("Pre-doctoral Research Assistant in Finance",
     "The University of Milan is hiring a predoctoral research assistant in finance. "
     "Applications are invited until 1 March 2025.",
     "expired"),
])
def test_unwanted_positions_are_dropped(title, text, reason):
    assert verdict(feed_item(title, text)) == reason


def test_rules_bind_a_model_too():
    """A confident Gemini answer still cannot publish a US bank job."""
    listing = PredocListing(
        title="Research Analyst, Monetary Policy", institution="Federal Reserve Bank of Boston",
        location=Location(country="United States", city="Boston"),
        apply_url="https://example.org/fed", source_url="https://example.org/fed",
        model_confidence=0.99, confidence=0.99,
    )
    item = feed_item(listing.title, "A research analyst position in monetary policy.")
    assert Policy(PREFS, trust_model_fields=True).check(listing, item) in (
        "industry-employer", "region-US", "not-academic-employer")


def test_board_items_carry_their_verdict():
    item = RawItem(source="predoc_org", source_url="https://bit.ly/x", title="Predoc",
                   text="...", hints={"board": True, "reject": "region-US"})
    listing = PredocListing(title="Predoc", institution="X University",
                            apply_url="https://bit.ly/x", source_url="https://bit.ly/x")
    assert POLICY.check(listing, item) == "region-US"


def test_board_item_without_employer_gets_placeholder_not_rejected():
    item = RawItem(source="jobs_ac_uk", source_url="https://www.jobs.ac.uk/job/ABC123/",
                   title="Research Assistant in Economics",
                   text="Research assistant in economics, London.",
                   hints={"board": True, "country": "United Kingdom", "region": "UK",
                          "strong": False})
    result = EXTRACTOR.extract(text=item.text, source_url=item.source_url, title=item.title,
                               hints=item.hints)
    listing = coerce(result, source_url=item.source_url)
    assert listing.institution == UNKNOWN_INSTITUTION
    assert POLICY.check(listing, item) is None


def test_clean_url_keeps_links_clickable():
    from predoc_pipeline.core.urls import canonicalize_url, clean_url, url_hash

    varbi = "https://su.varbi.com/en/what:job/jobID:971001/"
    assert clean_url(varbi) == varbi                       # ':' and '/' untouched
    assert clean_url("www.cemfi.es/news?id=1#top") == "https://www.cemfi.es/news?id=1"
    assert clean_url("https://x.org/a job/ü") == "https://x.org/a%20job/%C3%BC"
    assert clean_url("mailto:hr@x.org") == ""
    # identity is still the canonical form
    assert url_hash(varbi) == url_hash(canonicalize_url(varbi))
