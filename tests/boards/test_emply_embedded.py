"""Embedded JSON must remain data, with layout failures visible to discovery."""

import json

import pytest

from predoc_pipeline.boards.config import SourceConfig
from predoc_pipeline.boards.scrapers.emply_embedded import EmplyEmbeddedScraper


def scraper():
    return EmplyEmbeddedScraper(
        SourceConfig.model_validate(
            dict(
                name="emply_test",
                type="emply_embedded",
                url="https://university.example/jobs",
                job_path_prefix="/jobs/",
            )
        ),
        None,
    )


def page(data):
    return "<script>DYCON.EmplyData.c123.vacancies = " + json.dumps(data) + ";</script>"


def test_missing_and_malformed_data_are_failures_but_empty_array_is_valid():
    for html in [
        "<main>Login</main>",
        "<script>DYCON.EmplyData.c123.vacancies = alert(1);</script>",
        page({"jobs": []}),
    ]:
        instance = scraper()
        assert instance.parse_postings([("https://university.example/jobs", html)]) == []
        assert instance.discovery_parse_errors
    instance = scraper()
    assert instance.parse_postings([("https://university.example/jobs", page([]))]) == []
    assert not instance.discovery_parse_errors


@pytest.mark.parametrize(
    "entry",
    [
        None,
        {"title": "Research Assistant", "link": "https://other.example/jobs/1"},
        {"title": "", "link": "/jobs/1"},
        {"title": "Research Assistant", "link": "/jobs/1", "deadline_date": "2026-99-99"},
        {"title": "Research Assistant", "link": "/jobs/1", "location": "invalid"},
    ],
)
def test_invalid_entries_do_not_hide_valid_neighbor_or_execute_script(entry):
    instance = scraper()
    good = {
        "title": "Research Assistant",
        "link": "/jobs/123",
        "deadline_date": "2026-11-01",
        "start_date": "2027-01-01",
        "end_date": "2028-01-01",
        "registered_date": "2026-10-01",
        "location": {"name": "Aarhus"},
    }
    posts = instance.parse_postings([("https://university.example/jobs", page([entry, good]))])
    assert len(posts) == 1 and posts[0].url == "https://university.example/jobs/123"
    assert posts[0].deadline.isoformat() == "2026-11-01"
    assert posts[0].date_posted.isoformat() == "2026-10-01"
    assert posts[0].location == "Aarhus"
    assert instance.discovery_parse_errors == ["invalid Emply vacancy entry"]
