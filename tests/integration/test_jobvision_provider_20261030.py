"""Jobvision source contract: official public job IDs, real employers, no false alerts."""
from __future__ import annotations

import json
from datetime import date

import pytest

from predoc_pipeline.ingest.jobvision import (
    JOBVISION_SITEMAP,
    parse_jobvision_detail,
    parse_jobvision_sitemap,
)


def xml_links(*urls):
    return (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{url}</loc></url>" for url in urls)
        + "</urlset>"
    )


def detail(
    *, title="تحلیلگر داده", employer="شرکت داده نگار",
    country="IR", city="تهران", end="2099-12-14",
):
    return (
        "<html><head>"
        '<script type="application/ld+json">'
        + json.dumps({
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": title,
            "hiringOrganization": {"@type": "Organization", "name": employer},
            "jobLocation": {"@type": "Place", "address": {
                "@type": "PostalAddress", "addressCountry": country,
                "addressLocality": city,
            }},
            "validThrough": end,
        }, ensure_ascii=False)
        + "</script></head><body><h1>" + title + "</h1></body></html>"
    )


def test_jobvision_sitemap_returns_only_individual_official_job_ids():
    urls, more = parse_jobvision_sitemap(xml_links(
        "https://jobvision.ir/jobs/1511001/استخدام-تحلیلگر-داده",
        "https://www.jobvision.ir/jobs/1511001",
        "https://jobvision.ir/jobs/keyword/داده",
        "https://jobvision.ir/jobs",
        "https://attacker.example/jobs/1511002",
        "https://jobvision.ir/companies/example",
    ))
    assert urls == ["https://jobvision.ir/jobs/1511001"]
    assert more == []


def test_jobvision_sitemap_index_only_accepts_same_origin_job_sitemaps():
    data = (
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://jobvision.ir/jobs-sitemap.xml</loc></sitemap>"
        "<sitemap><loc>https://attacker.invalid/jobs-sitemap.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    jobs, more = parse_jobvision_sitemap(data)
    assert jobs == []
    assert more == ["https://jobvision.ir/jobs-sitemap.xml"]


def test_jobvision_structured_posting_is_canonical_and_has_real_employer_location():
    item = parse_jobvision_detail(
        detail(), "https://jobvision.ir/jobs/1511001/some-slug?utm_source=share",
        today=date(2026, 10, 30),
    )
    assert item is not None
    assert item["url"] == "https://jobvision.ir/jobs/1511001"
    assert item["title"] == "تحلیلگر داده"
    assert item["employer"] == "شرکت داده نگار"
    assert item["location"] == "تهران"
    assert item["category"] == "data_analyst"
    assert item["scope"] == "iran"
    assert item["source"] == "Jobvision"


@pytest.mark.parametrize("changes", [
    {"country": "US"}, {"employer": ""}, {"title": "مدیر فروش"},
    {"end": "2026-10-01"}, {"city": ""},
])
def test_jobvision_never_infers_employer_country_or_open_status(changes):
    assert parse_jobvision_detail(
        detail(**changes), "https://jobvision.ir/jobs/1511001",
        today=date(2026, 10, 30),
    ) is None


def test_jobvision_rejects_js_shell_without_jobposting_semantics():
    with pytest.raises(ValueError, match="JobPosting"):
        parse_jobvision_detail(
            "<html><h1>فرصت شغلی</h1><script>window.data=[]</script></html>",
            "https://jobvision.ir/jobs/1511001",
            today=date(2026, 10, 30),
        )


def test_jobvision_sitemap_rejects_html_and_external_entities():
    with pytest.raises(ValueError):
        parse_jobvision_sitemap("<!DOCTYPE root [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><root>&x;</root>")
    with pytest.raises(ValueError):
        parse_jobvision_sitemap("<html>SPA search results</html>")


def test_jobvision_sitemap_root_url_is_official():
    assert JOBVISION_SITEMAP == "https://jobvision.ir/sitemap.xml"


def test_jobvision_career_poll_is_staged_until_live_discovery_verified(
    tmp_path, monkeypatch,
):
    from types import SimpleNamespace

    from predoc_pipeline.ingest.career import poll_career

    monkeypatch.delenv("COLLEGEUM_JOBVISION_ENABLED", raising=False)

    class Client:
        def __init__(self):
            self.urls = []

        def get(self, url, **_kwargs):
            self.urls.append(url)
            if "jobinja" in url:
                body = '<a href="/companies/x/jobs/12/accountant">Accountant</a>'
            else:
                body = '<a href="/en/job/accountant/12345">Accountant</a>'
            return SimpleNamespace(ok=True, status=200, text=body, error="")

    client = Client()
    journal, health = tmp_path / "careers.ndjson", tmp_path / "career-health.json"
    new, errors = poll_career(
        journal, client=client, needs_iran=True, needs_remote=False,
        slot=0, health_path=health,
    )
    assert new == 0 and not errors
    assert all("jobvision.ir" not in url for url in client.urls)
    status = json.loads(health.read_text("utf-8"))["sources"]["jobvision"]
    assert status["status"] == "pending_validation"
    assert status["accepted"] == 0


def test_jobvision_opt_in_keeps_career_identity_dedupe_and_health(
    tmp_path, monkeypatch,
):
    from types import SimpleNamespace

    from predoc_pipeline.ingest.career import load_career, poll_career

    monkeypatch.setenv("COLLEGEUM_JOBVISION_ENABLED", "1")
    item_url = "https://jobvision.ir/jobs/1511001"

    class Client:
        def get(self, url, **_kwargs):
            if url == JOBVISION_SITEMAP:
                body = xml_links(item_url)
            elif url == item_url:
                body = detail()
            elif "jobinja" in url:
                body = '<a href="/companies/x/jobs/12/accountant">Accountant</a>'
            else:
                body = '<a href="/en/job/accountant/12345">Accountant</a>'
            return SimpleNamespace(ok=True, status=200, text=body, error="")

    client = Client()
    journal, health = tmp_path / "careers.ndjson", tmp_path / "career-health.json"
    first, errors = poll_career(
        journal, client=client, needs_iran=True, needs_remote=False,
        slot=0, health_path=health,
    )
    assert first == 1 and not errors
    second, errors = poll_career(
        journal, client=client, needs_iran=True, needs_remote=False,
        slot=0, health_path=health,
    )
    assert second == 0 and not errors
    records = load_career(journal)
    assert len(records) == 1 and records[0]["source"] == "Jobvision"
    status = json.loads(health.read_text("utf-8"))["sources"]["jobvision"]
    assert status["status"] == "ok" and status["accepted"] == 1


def test_jobvision_public_sitemap_utf16le_bom_can_reveal_nested_jobs_feed():
    xml = (
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://jobvision.ir/sitemap/jobposts.xml</loc></sitemap>"
        "</sitemapindex>"
    )
    malformed_decl = '<?xml version="1.0" encoding="utf-8"?>' + xml
    raw = b"\xff\xfe" + malformed_decl.encode("utf-16-le")
    jobs, nested = parse_jobvision_sitemap(raw)
    assert jobs == []
    assert nested == ["https://jobvision.ir/sitemap/jobposts.xml"]
