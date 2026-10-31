"""DKFZ publishes RSS XML only for clearly identified automated consumers.

Live GitHub runner #41191741843: default async HTTP 200 HTML; transparent
Collegeum User-Agent HTTP 200 RSS 2.0 with 16 entries. The same official URL
must be collected without browser rendering or a global user-agent change.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from predoc_pipeline.boards.config import SourceConfig
from predoc_pipeline.boards.scrapers.rss import RSSScraper
from predoc_pipeline.ingest.life_sciences import load_life_sources

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>DKFZ Job Publications</title>
<item><title>PhD Student in Epigenetics and Cancer Biology</title>
<link>https://jobs.dkfz.de/de/jobs/168938/phd-student-in-epigenetics</link>
<description>PhD research in gene regulation</description></item>
<item><title>Postdoctoral Fellow in Molecular Biology</title>
<link>https://jobs.dkfz.de/de/jobs/168939/postdoc-in-molecular-biology</link></item>
<item><title>Malicious source injection</title>
<link>https://jobs.dkfz.de.attacker.invalid/de/jobs/168940/malicious</link></item>
</channel></rss>"""


class FakeHttp:
    def __init__(self, feed=FEED):
        self.feed = feed
        self.calls = []

    def set_host_interval(self, *_args):
        return None

    async def get_text(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.feed


def _source():
    return SourceConfig(
        name="life_dkfz",
        type="rss",
        url="https://jobs.dkfz.de/en/jobs",
        institution="German Cancer Research Center (DKFZ)",
        country="Germany",
        require_deadline=True,
        rss_user_agent=(
            "Collegeum-LifeSciencesCollector/1.0 "
            "(+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
        ),
        allowed_link_hosts=["jobs.dkfz.de"],
    )


def test_dkfz_source_uses_employer_rss_and_approved_bot_identity():
    source = next(
        s for s in load_life_sources(Path("config/life_sciences.toml"))
        if s.name == "life_dkfz"
    )
    assert source.enabled is True
    assert source.type == "rss"
    assert source.opt("url") == "https://jobs.dkfz.de/en/jobs"
    assert source.opt("rss_user_agent").startswith("Collegeum-LifeSciencesCollector/")
    assert source.opt("allowed_link_hosts") == ["jobs.dkfz.de"]
    assert source.opt("require_deadline") is True


def test_identified_rss_request_preserves_jobs_and_rejects_foreign_host():
    http = FakeHttp()
    source = _source()
    scraper = RSSScraper(source, http)
    jobs, count = asyncio.run(scraper.run())
    assert count == 2
    assert len(jobs) == 2
    assert len(http.calls) == 1
    url, kwargs = http.calls[0]
    assert url == source.opt("url")
    assert kwargs["headers"]["User-Agent"].startswith("Collegeum-LifeSciencesCollector/")
    assert "rss+xml" in kwargs["headers"]["Accept"]
    assert jobs[0].url == (
        "https://jobs.dkfz.de/de/jobs/168938/phd-student-in-epigenetics"
    )
    assert jobs[0].title == "PhD Student in Epigenetics and Cancer Biology"
    assert jobs[0].extra["require_deadline"] is True
    assert jobs[0].country == "Germany"
    assert scraper.discovery_parse_errors == [
        "feed entry link host is not a trusted source hostname"
    ]


def test_default_rss_source_keeps_existing_http_request_contract():
    http = FakeHttp()
    source = SourceConfig(
        name="unrelated_rss", type="rss",
        url="https://feed.example.org/jobs",
    )
    scraper = RSSScraper(source, http)
    jobs, count = asyncio.run(scraper.run())
    assert count == 3
    assert len(jobs) == 3
    assert http.calls[0][1] == {}
    assert not scraper.discovery_parse_errors
