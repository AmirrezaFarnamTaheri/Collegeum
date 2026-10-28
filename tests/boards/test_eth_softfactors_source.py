"""ETH Law & Economics vacancies live in an official Softfactors JSON widget.

The source page's HTML is only a JavaScript placeholder. The provider feed is
ETH-wide, so we must filter by the widget's live organization identifiers.
"""

import asyncio
from datetime import date
from pathlib import Path

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS
from predoc_pipeline.core.health import source_status

PAGE = "https://lawecon.ethz.ch/group/open-positions.html"
FEED = (
    "https://lawecon.ethz.ch/group/open-positions/"
    "_jcr_content/par/jobs.softfactors.json"
)
JOB = "https://www.jobs.ethz.ch/job/en/12022?mw_source=jobs_ethz"


class FixtureHttp:
    def __init__(
        self,
        records,
        url_path="/group/open-positions/_jcr_content/par/jobs.softfactors.json",
        orgs="09629,09627,03795",
    ):
        self.records = records
        self.requests = []
        self.page = (
            '<div class="job-portal" data-init="jobs" data-orgs="' + orgs + '" '
            'data-url="' + url_path + '" data-to-portal-url="https://jobs.ethz.ch">'
            '<div data-is="JobPortal"></div></div>'
        )

    async def get_text(self, url):
        assert url == PAGE
        self.requests.append(url)
        return self.page

    async def get_json(self, url, **kwargs):
        assert url == FEED
        self.requests.append(url)
        return self.records


def record(ident="0z7L6XHbhhGWTMZS1r", classification="09629", title=None, url=JOB):
    return {
        "id": ident,
        "description": {
            "title": {
                "en": title or "Research Assistants (Law, Computer Science, or related fields)"
            },
            "eth_area": {"en": "Center for Law & Economics (D-GESS)"},
            "eth_intro": {"en": "<p>Data collection and AI research on law and society.</p>"},
        },
        "characterization": {"internalClassification": classification},
        "publication": {
            "publicationDate": "14.08.2026",
            "jobboardDetailUrl_en": url,
        },
    }


def source():
    return next(
        s for s in load_board_sources(Path("config/sources.toml"))
        if s.name == "eth_lawecon"
    )


def scrape(http):
    cfg = source()
    return asyncio.run(_scrape_all([SCRAPERS[cfg.type](cfg, http)], 1, 10))[0]


def test_live_eth_softfactors_feed_filters_by_center_and_preserves_original_job_url():
    cfg = source()
    assert cfg.type == "eth_softfactors"
    assert cfg.field_implied is False
    assert cfg.may_be_empty is True
    http = FixtureHttp([
        record("000000000000000000", classification="09999",
               title="Unrelated ETH engineering postdoc",
               url="https://www.jobs.ethz.ch/job/en/99999?mw_source=jobs_ethz"),
        record(),
    ])
    result = scrape(http)
    assert result.ok
    assert len(result.posts) == 1
    post = result.posts[0]
    assert post.title == "Research Assistants (Law, Computer Science, or related fields)"
    assert post.url == JOB
    assert post.date_posted == date(2026, 8, 14)
    assert post.deadline is None  # Publication date is NOT an application deadline.
    assert post.field_implied is False  # Law/CS posting must pass economic-field checks.
    assert post.institution == "ETH Zurich Center for Law & Economics"
    assert post.extra["eth_job_id"] == "0z7L6XHbhhGWTMZS1r"
    assert "Data collection" in post.description_snippet
    assert http.requests == [PAGE, FEED]


def test_explicit_center_organization_without_live_matching_jobs_is_normal_empty():
    result = scrape(FixtureHttp([
        record("000000000000000000", classification="09999")
    ]))
    assert result.ok
    assert result.posts == []
    assert source_status(result.as_stats()) == "empty"


def test_invalid_eth_vacancy_host_is_rejected_without_hiding_valid_job():
    http = FixtureHttp([
        record(url="https://www.jobs.ethz.ch.evil.invalid/job/en/12022"),
        record(ident="new01anotherValidID", url="https://www.jobs.ethz.ch/job/en/12023"),
    ])
    result = scrape(http)
    assert not result.ok
    assert len(result.posts) == 1
    assert result.posts[0].url == "https://www.jobs.ethz.ch/job/en/12023"
    assert result.as_stats()["failure_counts"]["parse"] == 1


def test_missing_widget_is_a_parse_failure_not_a_false_healthy_empty():
    http = FixtureHttp([])
    http.page = "<h1>Job Opportunities</h1>"
    result = scrape(http)
    assert not result.ok
    assert result.posts == []
    assert source_status(result.as_stats()) == "failed"
    assert result.as_stats()["failure_counts"]["parse"] >= 1


def test_unexpected_offsite_feed_is_never_requested():
    http = FixtureHttp([], url_path="https://evil.invalid/vacancies.json")
    result = scrape(http)
    assert not result.ok
    assert http.requests == [PAGE]
    assert source_status(result.as_stats()) == "failed"
