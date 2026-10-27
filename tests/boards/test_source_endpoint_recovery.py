"""Source route regressions grounded in official vacancy landing pages (Oct 2026)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS


def source(name):
    return next(s for s in load_board_sources(Path("config/sources.toml")) if s.name == name)


@pytest.mark.parametrize(("name", "expected_url"), [
    ("carlo_alberto", "https://www.carloalberto.org/about/jobs-fellowships/"),
    ("eth_lawecon", "https://lawecon.ethz.ch/group/open-positions.html"),
    ("iies_stockholm", "https://www.su.se/english/divisions/institute-for-international-economic-studies/about-the-institute/work-with-us"),
    ("iwh_halle", "https://www.iwh-halle.de/en/career/jobs/jobs-at-iwh"),
    ("opportunity_insights", "https://opportunityinsights.org/joinourteam/"),
    ("bde_spain", "https://www.bde.es/wbe/es/sobre-banco/trabajar-banco/convocatorias-plazo-abierto/"),
])
def test_removed_source_endpoints_are_replaced_with_official_pages(name, expected_url):
    assert source(name).opt("url") == expected_url


class FixtureHttp:
    def __init__(self, url, html):
        self.url, self.html = url, html

    async def get_text(self, url):
        assert url == self.url
        return self.html


def test_carlo_alberto_discovers_open_roles_but_never_closed_history():
    cfg = source("carlo_alberto")
    html = """
    <h2>CURRENTLY OPEN</h2>
    <a href="/about/jobs-fellowships/research-assistantships/">Research Assistantships</a>
    <a href="/about/jobs-fellowships/post-doctoral-position-new/">Post-doctoral position</a>
    <h2>CURRENTLY CLOSED</h2>
    <a href="/about/jobs-fellowships/research-assistant-in-2024/">Research Assistant in 2024</a>
    """
    result = asyncio.run(_scrape_all(
        [SCRAPERS[cfg.type](cfg, FixtureHttp(cfg.opt("url"), html))], 1, 5,
    ))[0]
    assert result.ok
    assert len(result.posts) == 2
    assert all("2024" not in post.url for post in result.posts)


def test_carlo_alberto_missing_closed_marker_is_not_treated_as_valid_empty():
    cfg = source("carlo_alberto")
    html = '<h2>CURRENTLY OPEN</h2><a href="/about/jobs-fellowships/ra/">Research Assistant</a>'
    result = asyncio.run(_scrape_all(
        [SCRAPERS[cfg.type](cfg, FixtureHttp(cfg.opt("url"), html))], 1, 5,
    ))[0]
    assert not result.ok
    assert result.as_stats()["errors"] > 0


def test_spanish_central_bank_links_match_actual_open_vacancies():
    import re

    cfg = source("bde_spain")
    role = ("https://www.bde.es/wbe/es/sobre-banco/trabajar-banco/"
            "becas-investigacion-ayudas-bde/"
            "personal-investigador-en-temas-de-economia-y-finanzas2026.html")
    assert re.search(cfg.opt("link_pattern"), role)
    assert not re.search(cfg.opt("link_pattern"), "https://www.bde.es/wbe/es/noticias/")

def test_iies_does_not_match_generic_university_jobs_index():
    import re
    pattern = source("iies_stockholm").opt("link_pattern")
    assert not re.search(pattern, "https://www.su.se/english/about/working-at-su/available-jobs")


def test_rwi_essen_routes_to_official_jobs_page_not_general_career_landing():
    cfg = source("rwi_essen")
    assert cfg.opt("url") == "https://www.rwi-essen.de/rwi/karriere/jobs"

def test_bis_official_vacancy_links_are_discovered():
    """The BIS migrated its vacancies to /vacancy/jrNNNNNN (verified 2026-10-28)."""
    import re

    cfg = source("bis")
    assert cfg.opt("url") == "https://www.bis.org/about/careers/vacancies"
    assert re.search(cfg.opt("link_pattern"), "https://www.bis.org/vacancy/jr100491")
    assert re.search(cfg.opt("link_pattern"), "https://www.bis.org/vacancy/jr100516")
    assert not re.search(cfg.opt("link_pattern"), "https://www.bis.org/about/careers/vacancies")

def test_uzh_department_jobs_page_exposes_current_predoc():
    """The university-wide jobs URL redirects to a JavaScript-only portal."""
    url = "https://www.econ.uzh.ch/en/about/jobs.html"
    link = (
        "https://jobs.uzh.ch/job-vacancies/"
        "pre-doctoral-program-global-talent-common-application/"
        "de0df20a-d294-46c1-8e4a-77db716745dc"
    )
    cfg = source("uzh")
    assert cfg.opt("url") == url
    html = f'<a href="{link}">Pre-Doctoral Program – Global Talent Common Application</a>'
    result = asyncio.run(_scrape_all([
        SCRAPERS[cfg.type](cfg, FixtureHttp(url, html))
    ], 1, 5))[0]
    assert result.ok
    assert [post.url for post in result.posts] == [link]
    assert "Pre-Doctoral" in result.posts[0].title


def test_niesr_uses_actual_careers_page_and_treats_advertised_empty_period_as_normal():
    """The old /about/vacancies route now opens an unrelated economics news article."""
    cfg = source("niesr")
    assert cfg.opt("url") == "https://niesr.ac.uk/careers"
    assert cfg.may_be_empty is True
    html = "<h2>Current vacancies</h2><p>Sorry, we do not have any vacancies at the moment</p>"
    result = asyncio.run(_scrape_all([
        SCRAPERS[cfg.type](cfg, FixtureHttp(cfg.opt("url"), html))
    ], 1, 5))[0]
    assert result.ok and result.as_stats()["errors"] == 0
    assert result.posts == []


def test_niesr_preserves_future_official_research_vacancy_discovery():
    cfg = source("niesr")
    url = "https://niesr.ac.uk/vacancy/research-assistant-in-economics"
    html = '<a href="/vacancy/research-assistant-in-economics">Research Assistant in Economics</a>'
    result = asyncio.run(_scrape_all([
        SCRAPERS[cfg.type](cfg, FixtureHttp(cfg.opt("url"), html))
    ], 1, 5))[0]
    assert result.ok
    assert [post.url for post in result.posts] == [url]
    assert result.posts[0].field_implied is True  # NIESR remains an economics institute.


def test_academictransfer_recovers_job_cards_with_empty_overlay_anchor():
    """Current cards have a full-area empty anchor and the real title in a sibling h3."""
    cfg = source("academictransfer")
    assert cfg.country is None  # Search is international; never invent a Dutch location.
    page = cfg.opt("urls")[0]
    cfg = cfg.model_copy(update={"urls": [page]})  # Isolate one configured search endpoint.
    html = """
    <article class="text-aqua-500 relative grid grid-cols-10 gap-6">
      <a class="absolute inset-0" href="/en/jobs/364701/assistant-professor-in-economics/"></a>
      <div class="col-span-10 md:col-span-6"><div>
        <h3>Assistant Professor in Economics</h3>
        <div class="col-start-1 col-end-11 md:col-start-8 md:col-end-11"><span class="text-at-small text-gray-700 md:text-right">Utrecht University</span></div>
      </div></div>
    </article>
    <article class="text-aqua-500 relative grid grid-cols-10 gap-6">
      <a class="absolute inset-0" href="/en/jobs/363610/researcher-economics-of-eu-common-agricultural-policy/"></a>
      <div><h3>Researcher - Economics of EU Common Agricultural Policy</h3>
        <div class="col-start-1 col-end-11 md:col-start-8 md:col-end-11"><span class="text-at-small text-gray-700 md:text-right">Wageningen University &amp; Research</span></div>
      </div>
    </article>
    """
    result = asyncio.run(_scrape_all([
        SCRAPERS[cfg.type](cfg, FixtureHttp(page, html))
    ], 1, 5))[0]
    assert result.ok
    assert [post.title for post in result.posts] == [
        "Assistant Professor in Economics",
        "Researcher - Economics of EU Common Agricultural Policy",
    ]
    assert result.posts[0].url == (
        "https://www.academictransfer.com/en/jobs/364701/assistant-professor-in-economics/"
    )
    assert all(post.country is None for post in result.posts)
    assert [post.institution for post in result.posts] == [
        "Utrecht University", "Wageningen University & Research",
    ]


def test_niesr_unrelated_news_page_must_not_be_treated_as_a_valid_empty_jobs_page():
    """Redirects or markup drift must not silently mask real vacancies."""
    cfg = source("niesr")
    html = "<h1>Vacancies Fall by Fastest Pace in Two Years</h1><p>Economic news</p>"
    result = asyncio.run(_scrape_all([
        SCRAPERS[cfg.type](cfg, FixtureHttp(cfg.opt("url"), html))
    ], 1, 5))[0]
    assert not result.ok
    assert result.as_stats()["errors"] > 0
    assert "parse" in result.as_stats()["failure_stage"]
