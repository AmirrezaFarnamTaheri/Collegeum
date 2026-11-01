"""Regression contract for Economic Misfit's official pre-doc category feed.

This test checks only routing; GitHub Actions production probes must separately
confirm RSS content and current employer-level vacancy eligibility.
"""
from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources


def test_economic_misfit_uses_current_category_not_obsolete_slug():
    sources = load_board_sources(Path("config/sources.toml"))
    source = next(item for item in sources if item.name == "economic_misfit")
    assert source.type == "rss"
    assert source.opt("urls") == [
        "https://theeconomicmisfit.com/category/opportunity-alert/pre-docs/feed/",
    ]
    assert "https://theeconomicmisfit.com/category/pre-docs/feed/" not in source.opt("urls")
    assert "https://theeconomicmisfit.com/feed/" not in source.opt("urls")
