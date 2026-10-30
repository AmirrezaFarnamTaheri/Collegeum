"""HKU research-source discovery: real departments, unique requisitions, and no medical false positives.

The live source was verified against HKU requisition 537693 (closing 2026-11-30).
Only a department supported by an individual vacancy advert may be admitted.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers.base import DiscoveryParseError
from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper


HKU_JOB = "https://jobs.hku.hk/en/job/537693/research-assistant-i"
MEDICAL_JOB = "https://jobs.hku.hk/en/job/537670/research-assistant-i"
FACULTY_JOB = "https://jobs.hku.hk/en/job/537762/senior-executive-assistant"
LISTING = "https://jobs.hku.hk/en/listing/"


def source():
    return next(
        item for item in load_board_sources(Path("config/sources.toml"))
        if item.name == "hku_econ_social_jobs"
    )


class FakeHttp:
    def __init__(self, html: str):
        self.html = html
        self.urls: list[str] = []

    async def get_text(self, url: str):
        self.urls.append(url)
        return self.html

    def set_host_interval(self, url: str, delay: float):
        pass


def page(*, full: bool = True):
    """Typical public HKU PageUp listing table; roles share a generic title."""
    return (
        "<h1>Current opportunities</h1><table>"
        '<tr><td>537693</td><td>'
        f'<a href="{HKU_JOB}">Research Assistant I</a></td>'
        '<td>Department of Real Estate and Construction (01200)</td>'
        '<td>Nov 30, 2026</td></tr>'
        '<tr><td>537670</td><td>'
        f'<a href="{MEDICAL_JOB}">Research Assistant I</a></td>'
        '<td>Department of Obstetrics and Gynaecology, School of Clinical Medicine (20900)</td>'
        '<td>Nov 9, 2026</td></tr>'
        + (
            '<tr><td>537762</td><td>'
            f'<a href="{FACULTY_JOB}">Senior Executive Assistant</a></td>'
            '<td>Faculty of Business and Economics (07000)</td>'
            '<td>Nov 18, 2026</td></tr>'
            if full else ""
        )
        + "</table>"
    )


def run(html: str, cfg=None):
    client = FakeHttp(html)
    posts, _ = asyncio.run(LinkScanScraper(cfg or source(), client).run())
    return posts, client


def test_registry_activates_one_distinct_official_hku_feed_with_department_gate():
    cfg = source()
    assert cfg.enabled
    assert cfg.country == "Hong Kong"
    assert cfg.institution == "University of Hong Kong"
    assert cfg.type == "link_scan"
    assert not cfg.field_implied
    assert cfg.opt("url") == LISTING
    assert cfg.opt("card_allow_pattern") and cfg.opt("title_allow_pattern")


def test_real_hku_econometric_research_role_beats_medical_and_faculty_false_positives():
    jobs, client = run(page())
    assert len(client.urls) == 1
    assert client.urls[0].startswith("https://jobs.hku.hk/")
    assert [job.url for job in jobs] == [HKU_JOB]
    assert jobs[0].title == "Research Assistant I"
    assert jobs[0].institution == "University of Hong Kong"
    assert jobs[0].country == "Hong Kong"
    assert jobs[0].field_implied is False
    assert all(job.url != MEDICAL_JOB for job in jobs)


def test_repeated_official_requisition_is_not_published_twice():
    posts, _ = run(page(full=False) + page(full=False))
    assert [job.url for job in posts] == [HKU_JOB]


def test_department_gate_ignores_generic_titles_without_supported_employer_unit():
    jobs, _ = run(
        "<table><tr><td><a href=\"" + MEDICAL_JOB + "\">"
        "Research Assistant I</a></td><td>School of Clinical Medicine</td></tr></table>"
    )
    assert jobs == []


def test_invalid_source_scoped_card_regex_is_reported_as_parser_failure():
    bad = source().model_copy(update={"card_allow_pattern": "("})
    with pytest.raises(DiscoveryParseError):
        run(page(), cfg=bad)
