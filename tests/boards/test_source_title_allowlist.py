"""Use opt-in source-specific title rules to prevent employer-wide ATS noise."""
import asyncio

import pytest

from predoc_pipeline.boards.config import SourceConfig
from predoc_pipeline.boards.scrapers.base import BaseScraper, DiscoveryParseError


class FixedRowsScraper(BaseScraper):
    type_name = "fixed-rows"

    async def fetch_raw_postings(self):
        return [
            "Predoctoral Research Assistant",
            "Postdoctoral Research Assistant",
            "Administrative Assistant",
            "Research Assistant/Sr. Research Assistant",
        ]

    def parse_postings(self, raw_data):
        return [
            self.make(title=title, url=f"https://example.org/job/{index}")
            for index, title in enumerate(raw_data)
        ]


def _run(pattern=None):
    opts = {"name": "test_employer", "type": "fixed-rows"}
    if pattern is not None:
        opts["title_allow_pattern"] = pattern
    return asyncio.run(FixedRowsScraper(SourceConfig.model_validate(opts), None).run())


def test_opt_in_title_allowlist_removes_off_role_ads_without_guessing_fields():
    posts, count = _run(r"^(?:Predoctoral Research Assistant|Research Assistant/Sr\. Research Assistant)$")
    assert count == 2
    assert {p.title for p in posts} == {
        "Predoctoral Research Assistant",
        "Research Assistant/Sr. Research Assistant",
    }


def test_title_allowlist_is_case_insensitive():
    posts, count = _run(r"^predoctoral research assistant$")
    assert count == 1
    assert posts[0].title == "Predoctoral Research Assistant"


def test_no_allowlist_preserves_all_legacy_source_rows():
    posts, count = _run()
    assert count == len(posts) == 4


def test_invalid_allowlist_fails_closed_instead_of_leaking_every_job():
    with pytest.raises(DiscoveryParseError):
        _run("[")
