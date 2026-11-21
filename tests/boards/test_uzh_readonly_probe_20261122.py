"""UZH source probe inspects only official anchor evidence without publishing."""

from __future__ import annotations

from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources
from tools.verify_uzh_live import inspect_html

INDEX = "https://www.econ.uzh.ch/en/about/jobs.html"
PREDOC = (
    "https://jobs.uzh.ch/job-vacancies/"
    "pre-doctoral-program-global-talent-common-application/"
    "de0df20a-d294-46c1-8e4a-77db716745dc"
)
STAFF = (
    "https://jobs.uzh.ch/offene-stellen/administrative-r-assistent-in/"
    "165d1e7d-35fb-4dc1-851a-2fe43a48339c"
)


def cfg():
    return next(
        source for source in load_board_sources(Path("config/sources.toml"))
        if source.name == "uzh"
    )


def test_official_uzh_employer_links_are_counted_separately_from_predocs() -> None:
    html = (
        "<h1>Open Positions</h1>"
        f'<a href="{PREDOC}">Pre-Doctoral Program - Global Talent</a>'
        f'<a href="{STAFF}">Administrative/r Assistent/in 40 %</a>'
        '<a href="https://jobs.uzh.ch.evil.example/offene-stellen/'
        'hijack/11111111-2222-3333-4444-555555555555">PhD jobs</a>'
        '<a href="https://www.uzh.ch/cmsssl/en/explore/work/jobs.html">'
        'Open faculty positions</a>'
    )
    result = inspect_html(cfg(), html)
    assert result["official_employer_links"] == 2
    assert result["parsed_vacancies"] == 2
    assert result["doctoral_title_signals"] == 1
    assert result["source_state"] == "vacancy-links-observed"
    assert result["parser_errors"] == 0
    assert "job-vacancies" not in str(result)  # no job URLs emitted


def test_changed_uzh_index_is_unverified_not_healthy_empty() -> None:
    html = (
        "<h1>Open Positions</h1>"
        '<a href="https://www.uzh.ch/cmsssl/en/explore/work/jobs.html">'
        'Further positions at UZH</a>'
        "<p>Those interested in pursuing a PhD may apply for admission.</p>"
    )
    result = inspect_html(cfg(), html)
    assert result["official_employer_links"] == 0
    assert result["parsed_vacancies"] == 0
    assert result["source_state"] == "unverified-empty"
    assert not result["verified_empty"]


def test_uzh_administrative_role_is_discovery_not_a_predoc() -> None:
    result = inspect_html(
        cfg(), f'<h1>Open Positions</h1><a href="{STAFF}">'
        "Administrative/r Assistent/in 40 %</a>",
    )
    assert result["official_employer_links"] == 1
    assert result["parsed_vacancies"] == 1
    assert result["doctoral_title_signals"] == 0
    assert result["source_state"] == "vacancy-links-observed"
