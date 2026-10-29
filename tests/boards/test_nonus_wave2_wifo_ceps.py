"""Prove that only job-specific, official WIFO and CEPS links are promoted."""
import asyncio
import re

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper

WIFO_JOB = (
    "https://www.wifo.ac.at/en/news/"
    "wifo-is-looking-for-a-phd-candidate-prae-doc-m-f-d-30-hours-week/"
)
CEPS_CLIMATE = (
    "https://cdn.ceps.eu/2026/10/"
    "ERCC_Vacancy_Research-Assistant_October-2026.pdf"
)
CEPS_ENLARGEMENT = (
    "https://cdn.ceps.eu/2026/10/Job-advert-enlargement-programme.pdf"
)


def config(name):
    return next(s for s in load_board_sources("config/sources.toml") if s.name == name)


class StubHttp:
    def __init__(self, page):
        self.page = page

    async def get_text(self, url):
        assert url.startswith("https://")
        return self.page

    def set_host_interval(self, url, delay):
        assert delay >= 0


def collect(name, html):
    source = config(name)
    rows, _ = asyncio.run(LinkScanScraper(source, StubHttp(html)).run())
    return rows


def test_wifo_live_energy_economics_predoc_is_admitted_but_staff_is_not():
    source = config("wifo_austria_jobs")
    assert source.enabled and not source.field_implied
    assert source.country == "Austria"
    assert re.search(source.opt("link_pattern"), WIFO_JOB, re.I)
    html = (
        f'<a href="{WIFO_JOB}">WIFO is Looking for a PhD Candidate, '
        "Prae-Doc (m/f/d, 30 hours/week)</a>"
        '<a href="https://www.wifo.ac.at/en/news/wifo-is-looking-for-an-'
        'economist-30-39-hours-week/">WIFO is Looking for an Economist</a>'
    )
    rows = collect(source.name, html)
    # JobPostSchema canonicalizes a trailing slash in vacancy identity.
    assert [row.url for row in rows] == [WIFO_JOB.rstrip("/")]
    assert all(row.field_implied is False for row in rows)


def test_ceps_live_research_assistants_are_distinct_and_managers_rejected():
    source = config("ceps_brussels_research")
    assert source.enabled and not source.field_implied
    assert source.country == "Belgium"
    assert all(re.search(source.opt("link_pattern"), u, re.I)
               for u in (CEPS_CLIMATE, CEPS_ENLARGEMENT))
    html = (
        f'<a href="{CEPS_CLIMATE}">Research Assistant – '
        "Green transition and sustainable societies (ERCC Unit)</a>"
        f'<a href="{CEPS_ENLARGEMENT}">Research Assistant – '
        "Enlargement Programme (Foreign Policy Unit)</a>"
        '<a href="https://cdn.ceps.eu/2026/10/Job-advert-Programmes-'
        'and-Partnership-Manager.pdf">Programmes and Partnership Manager</a>'
        '<a href="https://www.ceps.eu/about-ceps/career-opportunities/">'
        "Open Positions</a>"
    )
    rows = collect(source.name, html)
    assert {row.url for row in rows} == {CEPS_CLIMATE, CEPS_ENLARGEMENT}
    assert len(rows) == 2
    assert all(row.field_implied is False for row in rows)


def test_wave2_keeps_unverified_nonus_candidates_disabled():
    names = {
        "wifo_austria_jobs", "ceps_brussels_research", "nus_policy_research",
        "hku_econ_social_jobs", "liser_luxembourg_jobs",
    }
    status = {s.name: s.enabled for s in load_board_sources("config/sources.toml")
              if s.name in names}
    assert status == {
        "wifo_austria_jobs": True,
        "ceps_brussels_research": True,
        "nus_policy_research": True,
        "hku_econ_social_jobs": False,
        "liser_luxembourg_jobs": False,
    }
