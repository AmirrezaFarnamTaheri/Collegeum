"""DZNE d.vinci public sitemap and jobPublication XML regression contract.

GitHub runner 41064734952 verified the employer's current XML field names;
101677 is a current Magdeburg neuroscience PhD closing 2026-12-01.
"""
from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from predoc_pipeline.boards.config import SourceConfig
from predoc_pipeline.boards.scrapers.base import DiscoveryFetchError
from predoc_pipeline.boards.scrapers.dzne_sitemap import DzneSitemapScraper
from predoc_pipeline.ingest.life_sciences import classify_post, load_life_sources

SITEMAP = "https://jobs.dzne.de/sitemap.xml"
PHD = (
    "https://jobs.dzne.de/en/jobs/101677/"
    "phd-researcher-fmx-laminar-7t-fmri-of-medial-temporal-lobe-hyperactivity-"
    "in-aging-and-alzheimers-disease-1578202610"
)
POSTDOC = (
    "https://jobs.dzne.de/en/jobs/101668/"
    "postdoctoral-researcher-fmx-remote-and-unsupervised-smartphone-"
    "based-assessments-in-early-alzheimers-disease-407020269"
)
STAFF = "https://jobs.dzne.de/de/jobs/101671/ausbildung-kaufleute-buromanagement-157220269"
APPLY = "https://jobs.dzne.de/en/jobs/101677/apply"


def config(**changes):
    vals = dict(
        name="life_special_de_dzne", type="dzne_sitemap", enabled=True,
        url=SITEMAP, institution="German Center for Neurodegenerative Diseases",
        country="Germany", field_implied=False,
        max_details=12,
    )
    vals.update(changes)
    return SourceConfig(**vals)


def sitemap(*links):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{escape(url)}</loc></url>" for url in links)
        + "</urlset>"
    )


def detail(
    *, title="PhD Researcher (f/m/x) - Laminar 7T fMRI in Alzheimer's Disease",
    end="2026-12-01T22:59:59.999Z", ident="101677", apply=APPLY,
    actual_url=PHD,
):
    fields = {
        "id": ident, "language": "en", "position": title,
        "jobPublicationURL": actual_url, "applicationFormURL": apply,
        "startDate": "2026-10-19T22:00Z", "endDate": end,
        "tasks": "<p>PhD student in the Multimodal Neuroimaging Group at DZNE "
                 "Magdeburg researching Alzheimer's disease and neurobiology.</p>",
        "profile": "<p>Master's degree in neuroscience or biomedical sciences "
                   "is required to enter the PhD position.</p>",
    }
    return "<?xml version='1.0'?><jobPublication>" + "".join(
        f"<{k}>{escape(v)}</{k}>" for k, v in fields.items()
    ) + "</jobPublication>"


class Http:
    def __init__(self, pages):
        self.pages = pages
        self.urls = []

    async def get_text(self, url):
        self.urls.append(url)
        return self.pages[url]


def collect(pages, cfg=None):
    client = Http(pages)
    scraper = DzneSitemapScraper(cfg or config(), client)
    posts, _ = asyncio.run(scraper.run())
    return posts, client, scraper


def test_existing_dzne_candidate_is_activated_without_registry_duplicate():
    matches = [
        s for s in load_life_sources(Path("config/life_sciences.toml"))
        if s.name == "life_special_de_dzne"
    ]
    assert len(matches) == 1
    assert matches[0].enabled
    assert matches[0].type == "dzne_sitemap"
    assert matches[0].opt("url") == SITEMAP
    assert matches[0].institution == "German Center for Neurodegenerative Diseases"


def test_official_sitemap_discovers_current_phd_and_rejects_postdoc_staff_and_external():
    pages = {SITEMAP: sitemap(PHD, POSTDOC, STAFF, "https://evil.test/en/jobs/101688/phd") ,
             PHD: detail()}
    posts, http, scraper = collect(pages)
    assert [post.url for post in posts] == [PHD]
    assert http.urls == [SITEMAP, PHD]
    assert posts[0].date_posted == date(2026, 10, 19)
    assert posts[0].deadline == date(2026, 12, 1)
    assert "Master" in posts[0].description_snippet
    assert "neuroscience" in posts[0].description_snippet.lower()
    assert posts[0].country == "Germany"
    assert posts[0].institution == "German Center for Neurodegenerative Diseases"
    assert posts[0].extra["application_form_url"] == APPLY
    assert not scraper.discovery_parse_errors
    matched = classify_post(posts[0], today=date(2026, 10, 30))
    assert matched is not None
    assert matched["deadline"] == "2026-12-01"
    assert matched["funding_status"] == "unverified"


def test_duplicate_language_or_same_requisition_does_not_realert():
    de = PHD.replace("/en/jobs/", "/de/jobs/")
    posts, client, _ = collect({SITEMAP: sitemap(PHD, de, PHD), PHD: detail()})
    assert [p.url for p in posts] == [PHD]
    assert client.urls == [SITEMAP, PHD]


@pytest.mark.parametrize("bad", [
    "<html><body>No posts</body></html>",
    "<!DOCTYPE test [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><urlset>&x;</urlset>",
    "<urlset><url><loc>https://evil.test</loc></url>",
])
def test_broken_or_unsafe_sitemap_never_becomes_healthy_empty(bad):
    with pytest.raises(DiscoveryFetchError):
        collect({SITEMAP: bad})


def test_valid_sitemap_without_doctoral_roles_is_a_verified_empty_period():
    posts, client, scraper = collect({SITEMAP: sitemap(STAFF, POSTDOC)})
    assert posts == []
    assert client.urls == [SITEMAP]
    assert scraper.verified_empty_evidence


def test_mismatched_individual_job_identity_has_parse_error_not_false_empty():
    posts, _, scraper = collect({
        SITEMAP: sitemap(PHD), PHD: detail(ident="999999"),
    })
    assert posts == []
    assert scraper.discovery_parse_errors
    assert not scraper.verified_empty_evidence


def test_expired_phd_or_wrong_applicant_route_is_not_published():
    posts, _, scraper = collect({
        SITEMAP: sitemap(PHD),
        PHD: detail(end="2026-10-01T22:00:00Z"),
    })
    assert posts == []
    assert not scraper.discovery_parse_errors

    posts, _, scraper = collect({
        SITEMAP: sitemap(PHD),
        PHD: detail(apply="https://attacker.test/en/jobs/101677/apply"),
    })
    assert posts == []
    assert scraper.discovery_parse_errors


def test_invalid_source_config_fails_before_any_network_request():
    http = Http({})
    scraper = DzneSitemapScraper(
        config(url="https://attacker.test/sitemap.xml"), http,
    )
    with pytest.raises(DiscoveryFetchError):
        asyncio.run(scraper.run())
    assert http.urls == []


def test_unbounded_candidate_count_is_reported_as_limit_not_silent_success():
    many = [
        f"https://jobs.dzne.de/en/jobs/{101677+i}/phd-researcher-test-{i}"
        for i in range(20)
    ]
    data = {SITEMAP: sitemap(*many)}
    for index, link in enumerate(many[:12]):
        data[link] = detail(
            ident=str(101677+index), actual_url=link,
            apply=f"https://jobs.dzne.de/en/jobs/{101677+index}/apply",
        )
    posts, client, scraper = collect(data)
    assert len(posts) == 12
    assert len(client.urls) == 13
    assert scraper.discovery_limits
