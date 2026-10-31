"""Keep per-vacancy BIS RSS geography distinct from employer headquarters.

The official 31 October 2026 RSS has a Hong Kong research analyst vacancy
alongside Basel roles. Title/description evidence must be known before
the general collector's pre-enrichment geographic eligibility gate.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from predoc_pipeline.boards.config import SourceConfig, load_board_sources
from predoc_pipeline.boards.scrapers.rss import RSSScraper

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/sources.toml"


class FakeHttp:
    def __init__(self, xml: str) -> None:
        self.xml = xml

    def set_host_interval(self, *_args) -> None:
        pass

    async def get_text(self, _url: str, **_kwargs) -> str:
        return self.xml


def _bis():
    return next(s for s in load_board_sources(CONFIG) if s.name == "bis")


def _job(title: str, url: str, details: str) -> str:
    return (
        f"<item><title>{title}</title><link>{url}</link>"
        f"<description>{details}</description></item>"
    )


def _feed() -> str:
    items = [
        _job(
            "Data Scientist / Research Analyst",
            "https://www.bis.org/vacancy/jr100491",
            "BIS headquarters are in Basel, Switzerland; however this role "
            "is based in Hong Kong SAR. Economic research and financial markets.",
        ),
        _job(
            "Research Assistant in Economics",
            "https://www.bis.org/vacancy/jr100516",
            "This role is based in Basel, Switzerland. Economic policy research.",
        ),
        _job(
            "Research Analyst, location not stated",
            "https://www.bis.org/vacancy/jr100527",
            "The bank headquarters are in Basel, Switzerland. "
            "Workplace for this vacancy has not been specified.",
        ),
    ]
    return '<rss version="2.0"><channel><title>BIS Jobs</title>' + "".join(items) + "</channel></rss>"


def test_bis_opts_into_explicit_rss_workplace_evidence_without_swiss_default():
    cfg = _bis()
    assert cfg.enabled
    assert cfg.type == "rss"
    assert cfg.country is None
    assert cfg.opt("infer_country_from_summary") is True


def test_explicit_vacancy_workplace_is_not_overridden_by_earlier_headquarters():
    posts, count = asyncio.run(RSSScraper(_bis(), FakeHttp(_feed())).run())
    assert count == 3
    by_id = {p.url.rsplit("/", 1)[-1]: p for p in posts}
    assert by_id["jr100491"].country == "Hong Kong"
    assert by_id["jr100491"].location == "Hong Kong SAR"
    assert by_id["jr100516"].country == "Switzerland"
    assert by_id["jr100516"].location == "Basel, Switzerland"
    assert by_id["jr100527"].country is None
    assert by_id["jr100527"].location is None
    assert all("source_country_default" not in p.extra for p in posts)


def test_workplace_summary_inference_remains_off_for_other_rss_sources():
    cfg = SourceConfig(name="other", type="rss", url="https://example.org/rss")
    posts, count = asyncio.run(RSSScraper(cfg, FakeHttp(_feed())).run())
    assert count == 3
    assert all(p.country is None and p.location is None for p in posts)
