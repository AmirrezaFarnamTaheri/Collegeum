"""A failed Life Sciences detail request is partial collection, not a healthy discovery."""
from __future__ import annotations

import asyncio

from predoc_pipeline.boards.config import HttpConfig
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.ingest import life_sciences


class StubHttpContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


def test_failed_job_detail_downgrades_source_health_without_discarding_jobs(
    tmp_path, monkeypatch,
):
    config = tmp_path / "life_sciences.toml"
    config.write_text(
        '[[board]]\nname="life_detail_broken"\ntype="link_scan"\n'
        'url="https://example.org/jobs"\nlink_pattern="example.org/job/"\n'
        '[[board]]\nname="life_detail_healthy"\ntype="link_scan"\n'
        'url="https://example.org/jobs"\nlink_pattern="example.org/job/"\n',
        encoding="utf-8",
    )

    class Scraper:
        def __init__(self, source, _http):
            self.source = source
            self.discovery_fetch_errors = []
            self.discovery_parse_errors = []
            self.discovery_limits = []

        async def run(self):
            return [
                JobPostSchema(
                    title="PhD Position in Epigenetics",
                    source=self.source.name,
                    url=f"https://example.org/job/{self.source.name}",
                    institution="Example University",
                    country="",
                    location="",
                    description_snippet="",
                )
            ], 1

        async def fetch_detail(self, _post):
            if self.source.name == "life_detail_broken":
                raise TimeoutError("Detail page timed out")
            return "Research in epigenetics at Example University."

    monkeypatch.setattr(life_sciences, "SCRAPERS", {"link_scan": Scraper})
    monkeypatch.setattr(life_sciences, "build_http", lambda _cfg: StubHttpContext())
    diagnostics = {}
    postings, errors = asyncio.run(
        life_sciences.discover(config, HttpConfig(), diagnostics=diagnostics)
    )

    assert len(postings) == 2  # Preserve listing-only candidates for later vetting.
    assert errors == []  # Do not turn an optional detail into a source-level outage.
    assert diagnostics["life_detail_broken"]["detail_failures"] == 1
    assert diagnostics["life_detail_broken"]["vacancy_links"] == 1
    assert diagnostics["life_detail_broken"]["status"] == "partial"
    assert diagnostics["life_detail_healthy"]["detail_failures"] == 0
    assert diagnostics["life_detail_healthy"]["status"] == "discovered"
