"""Failure and identity boundaries for plain-text vacancy tables."""

import pytest

from predoc_pipeline.boards.config import SourceConfig
from predoc_pipeline.boards.scrapers.text_table import TextTableScraper


def scraper(**options):
    return TextTableScraper(
        SourceConfig.model_validate(
            dict(
                name="table_test",
                type="text_table",
                url="https://university.example/jobs",
                table_selector="#jobs",
                job_path_prefix="/jobs/",
                columns={"title": 0, "url": 1},
                **options,
            )
        ),
        None,
    )


def test_missing_table_is_reported_but_present_empty_table_is_seasonal():
    instance = scraper()
    assert (
        instance.parse_postings([("https://university.example/jobs", "<main>Login</main>")]) == []
    )
    assert instance.discovery_parse_errors == ["vacancy table missing"]
    instance = scraper()
    assert (
        instance.parse_postings([("https://university.example/jobs", '<table id="jobs"></table>')])
        == []
    )
    assert not instance.discovery_parse_errors


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://[invalid/jobs/1",
        "https://other.example/jobs/1",
        "http://university.example/jobs/1",
        "https://user:password@university.example/jobs/1",
        "https://university.example/news/1",
    ],
)
def test_untrusted_or_non_vacancy_text_urls_fail_without_hiding_valid_neighbors(url):
    instance = scraper()
    html = f'<table id="jobs"><tr><th>Title</th><th>URL</th></tr><tr><td>Bad</td><td>{url}</td></tr><tr><td>Research Assistant</td><td>https://university.example/jobs/123</td></tr></table>'
    posts = instance.parse_postings([("https://university.example/jobs", html)])
    assert len(posts) == 1 and posts[0].title == "Research Assistant"
    assert instance.discovery_parse_errors == ["invalid vacancy title or URL"]


def test_incomplete_row_is_reported():
    instance = scraper()
    assert (
        instance.parse_postings(
            [
                (
                    "https://university.example/jobs",
                    '<table id="jobs"><tr><td>Research Assistant</td></tr></table>',
                )
            ]
        )
        == []
    )
    assert instance.discovery_parse_errors == ["incomplete vacancy row"]
