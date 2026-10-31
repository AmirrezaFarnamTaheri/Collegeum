"""BIS recovery: preserve conservative RSS 1.0 and source-budget contracts.

These cases bridge PR #93 (official RSS discovery) and PR #94
(job-specific geography). They must pass together after reconciliation.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers.rss import RSSScraper


ROOT = Path(__file__).resolve().parents[2]
HK_JOB = "https://www.bis.org/vacancy/jr100491"
BASEL_JOB = "https://www.bis.org/vacancy/jr100516"


class Http:
    def set_host_interval(self, *_args: object) -> None:
        pass

    async def get_text(self, _url: str, **_kwargs: object) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
            ' xmlns="http://purl.org/rss/1.0/">'
            '<channel rdf:about="https://www.bis.org/doclist/vacancies.rss">'
            '<title>BIS current vacancies</title>'
            '</channel>'
            f'<item rdf:about="{HK_JOB}">'
            '<title>Data Scientist / Research Analyst</title>'
            f'<link>{HK_JOB}</link>'
            '<description>Hong Kong position in banking research.</description>'
            '</item>'
            f'<item rdf:about="{BASEL_JOB}">'
            '<title>2027 PhD Fellowship Programme</title>'
            f'<link>{BASEL_JOB}</link>'
            '<description>Basel, Switzerland fellowship.</description>'
            '</item>'
            '</rdf:RDF>'
        )


def _bis_source():
    return next(
        s for s in load_board_sources(ROOT / "config/sources.toml")
        if s.name == "bis"
    )


def test_bis_keeps_explicit_politeness_and_timeout_bounds():
    source = _bis_source()
    assert source.enabled
    assert source.type == "rss"
    assert not source.may_be_empty
    assert source.min_interval is not None and source.min_interval >= 3.0
    assert source.source_timeout_seconds is not None
    assert source.source_timeout_seconds <= 45.0
    assert source.country is None


def test_bis_rss1_vague_workplace_is_not_treated_as_verified_country():
    scraper = RSSScraper(_bis_source(), Http())
    postings, count = asyncio.run(scraper.run())
    assert count == 2
    assert {post.url for post in postings} == {HK_JOB, BASEL_JOB}
    assert all(post.country is None for post in postings)
    assert all(post.location is None for post in postings)
    assert scraper.discovery_parse_errors == []


def test_legacy_bis_live_verifier_must_not_force_all_jobs_to_unknown_country():
    workflow = ROOT / ".github/workflows/verify-bis-official-rss-live.yml"
    assert workflow.exists(), "Preserve the existing manually runnable BIS probe"
    content = workflow.read_text(encoding="utf-8")
    assert "assert job.country is None" not in content
    assert "source_country_default" in content
