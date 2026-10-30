"""Conservative Jobvision public vacancy parsing (no private or undocumented APIs).

A source is not live merely because a homepage loads. Only official sitemap
individual job IDs and structured JobPosting employer/location/deadline proof
can produce a career job. Collection is separately feature-gated pending a
successful robots-aware Github-runner acceptance.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup

JOBVISION_SITEMAP = "https://jobvision.ir/sitemap.xml"
_JOB_PATH = re.compile(r"/jobs/([1-9]\d{3,10})(?:/[^?#]+)?/?$")
_MAX_XML_BYTES = 8 * 1024 * 1024


def _job_url(value: str) -> str | None:
    try:
        url = urlsplit(value.strip())
    except ValueError:
        return None
    if url.scheme != "https" or url.hostname not in {"jobvision.ir", "www.jobvision.ir"}:
        return None
    match = _JOB_PATH.fullmatch(url.path)
    if not match:
        return None
    return f"https://jobvision.ir/jobs/{match.group(1)}"


def parse_jobvision_sitemap(text: str | bytes) -> tuple[list[str], list[str]]:
    """Return canonical job IDs and same-host nested jobs sitemap URLs.

    Other domains, category indexes, search queries and SEO pages cannot
    become individual applications. XML external-entity declarations fail.
    """
    if isinstance(text, bytes):
        if len(text) > _MAX_XML_BYTES:
            raise ValueError("Jobvision sitemap exceeds limit")
        try:
            if text.startswith((b"\xff\xfe", b"\xfe\xff")):
                text = text.decode("utf-16")
            else:
                text = text.decode("utf-8-sig")
        except UnicodeError as exc:
            raise ValueError("Jobvision sitemap has invalid encoding") from exc
    if len(text.encode("utf-8")) > _MAX_XML_BYTES or "<!DOCTYPE" in text.upper():
        raise ValueError("Jobvision sitemap exceeds limit or contains a DTD")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ValueError("Jobvision returned invalid sitemap XML") from exc
    localname = root.tag.rsplit("}", 1)[-1]
    if localname not in {"sitemapindex", "urlset"}:
        raise ValueError("Jobvision returned an unsupported sitemap root")
    urls: list[str] = []
    sitemaps: list[str] = []
    for parent in root:
        for child in parent:
            if child.tag.rsplit("}", 1)[-1] != "loc":
                continue
            link = (child.text or "").strip()
            if localname == "urlset":
                job = _job_url(link)
                if job and job not in urls:
                    urls.append(job)
            else:
                parts = urlsplit(link)
                if (parts.scheme == "https"
                        and parts.hostname in ("jobvision.ir", "www.jobvision.ir")
                        and not parts.query and not parts.fragment
                        and parts.path.lower().endswith(".xml")
                        and "job" in parts.path.lower()
                        and "sitemap" in parts.path.lower()
                        and link not in sitemaps):
                    sitemaps.append(link)
    return urls, sitemaps


def _find_postings(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [posting for x in data for posting in _find_postings(x)]
    if not isinstance(data, dict):
        return []
    typ = data.get("@type", "")
    if isinstance(typ, str) and typ.lower() == "jobposting":
        return [data]
    if isinstance(typ, list) and "JobPosting" in typ:
        return [data]
    return _find_postings(data.get("@graph", []))


def parse_jobvision_detail(
    html: str, url: str, *, today: date | None = None,
) -> dict[str, str] | None:
    """Accept a current, geographically explicit JobPosting with real employer.

    Returns None for closed, off-field, unverifiable or invalid postings.
    Missing usable structured data is a *schema failure*, never healthy empty.
    """
    from .career import _job

    canonical = _job_url(url)
    if canonical is None:
        return None
    soup = BeautifulSoup(html, "lxml")
    postings: list[dict[str, Any]] = []
    for node in soup.select('script[type="application/ld+json"]')[:30]:
        try:
            postings.extend(_find_postings(json.loads(node.string or node.get_text())))
        except (TypeError, ValueError):
            continue
    if not postings:
        raise ValueError("Jobvision page has no structured JobPosting")
    reference = today or date.today()
    for data in postings:
        title = data.get("title")
        org = data.get("hiringOrganization")
        end = data.get("validThrough")
        location = data.get("jobLocation")
        if (not isinstance(title, str) or not isinstance(org, dict)
                or not isinstance(end, str) or not isinstance(location, dict)):
            continue
        employer = org.get("name")
        address = location.get("address")
        if (not isinstance(employer, str) or not employer.strip()
                or employer.strip().casefold() in {"jobvision", "جاب ویژن", "جاب‌ویژن"}
                or not isinstance(address, dict)):
            continue
        country = address.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        city = address.get("addressLocality")
        if (country not in {"IR", "Iran", "ایران"}
                or not isinstance(city, str) or not city.strip()):
            continue
        try:
            expires = date.fromisoformat(end[:10])
        except ValueError:
            continue
        if expires < reference:
            continue
        return _job(
            url=canonical, title=title.strip(), employer=employer.strip(),
            location=city.strip(), source="Jobvision", scope="iran",
        )
    return None


def collect_jobvision(client: Any, *, max_details: int = 8) -> tuple[list[dict[str, str]], int]:
    """Read at most two nested public sitemaps and eight posting pages.

    Any sitemap failure is an error, not proof of zero live vacancies.
    The caller's PoliteClient enforces robots, network safety and pacing.
    """
    if not 1 <= max_details <= 8:
        raise ValueError("Jobvision detail budget must be between one and eight")
    fetched = 0

    def fetch_bytes(url: str) -> bytes:
        nonlocal fetched
        res = client.get(url, use_cache=False)
        fetched += 1
        if not res.ok:
            raise ValueError(f"Jobvision official source unavailable: {res.error or res.status}")
        return bytes(res.content)

    def fetch(url: str) -> str:
        nonlocal fetched
        res = client.get(url, use_cache=False)
        fetched += 1
        if not res.ok:
            raise ValueError(f"Jobvision official source unavailable: {res.error or res.status}")
        return str(res.text)

    # The official site currently serves a UTF-16LE sitemap with an
    # inconsistent XML encoding declaration. Parse response bytes directly.
    jobs, nested = parse_jobvision_sitemap(fetch_bytes(JOBVISION_SITEMAP))
    for sub in nested[:2]:
        child_jobs, _ = parse_jobvision_sitemap(fetch_bytes(sub))
        jobs.extend(child_jobs)
    jobs = list(dict.fromkeys(jobs))
    if not jobs:
        raise ValueError("Jobvision sitemap has no discoverable individual job URLs")
    results: list[dict[str, str]] = []
    errors = 0
    for url in jobs[:max_details]:
        try:
            item = parse_jobvision_detail(fetch(url), url)
            if item:
                results.append(item)
        except ValueError:
            errors += 1
    if errors == min(max_details, len(jobs)):
        raise ValueError("Jobvision job pages are unavailable or have no verifiable schema")
    return results, fetched
