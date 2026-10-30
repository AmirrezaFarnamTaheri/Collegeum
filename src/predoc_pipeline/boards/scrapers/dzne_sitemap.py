"""Official DZNE d.vinci sitemap and jobPublication XML doctoral feed.

The public HTML search is a JavaScript shell. Employer-controlled XML provides
individual vacancy identity, application link, full eligibility and expiry.
Only current doctoral candidates are fetched, with strict origin and budgets.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

from ..models import JobPostSchema
from ..utils.dates import parse_iso_datetime
from ..utils.text import html_to_text, truncate
from .base import BaseScraper, register

_SITEMAP = "https://jobs.dzne.de/sitemap.xml"
_JOB = re.compile(r"^/(en|de)/jobs/([1-9]\d{4,8})/([a-z0-9][a-z0-9-]{6,240})/?$")
_ROLE = re.compile(r"phd|doktorand|doctorand|(?<!post)doctoral|promotion", re.I)
_EXCLUDE = re.compile(r"(?:^|[-_])post[-_]?doc(?:toral)?(?:[-_]|$)", re.I)
_MAX_SITEMAP = 800_000
_MAX_DETAIL = 200_000


def _vacancy_parts(url: str) -> tuple[str, str, str] | None:
    try:
        part = urlsplit(url)
        if (
            part.scheme != "https" or part.hostname != "jobs.dzne.de"
            or part.username or part.password or part.port not in (None, 443)
            or part.query or part.fragment
        ):
            return None
        match = _JOB.fullmatch(part.path)
        if not match:
            return None
        return match.group(1), match.group(2), match.group(3)
    except ValueError:
        return None


def _candidate(url: str) -> bool:
    parts = _vacancy_parts(url)
    if parts is None:
        return False
    slug = parts[2]
    return bool(_ROLE.search(slug) and not _EXCLUDE.search(slug))


def _xml(text: str, expected_tag: str, max_chars: int) -> ElementTree.Element:
    if len(text) > max_chars or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("DZNE XML size or DTD contract invalid")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise ValueError("DZNE official recruitment XML invalid") from exc
    if root.tag.rsplit("}", 1)[-1] != expected_tag:
        raise ValueError("DZNE official recruitment XML has wrong root")
    return root


def _field(root: ElementTree.Element, name: str) -> str:
    return (root.findtext(name) or "").strip()


@register
class DzneSitemapScraper(BaseScraper):
    """Extract only job-ID-backed PhD vacancies published in DZNE's live sitemap."""

    type_name = "dzne_sitemap"

    async def fetch_raw_postings(self) -> list[Any]:
        if (
            self.name != "life_special_de_dzne"
            or self.opt("url") != _SITEMAP
            or self.cfg.institution != "German Center for Neurodegenerative Diseases"
            or self.cfg.country != "Germany"
        ):
            raise ValueError("Invalid DZNE official recruitment source configuration")
        maximum = self.opt("max_details", 12)
        if type(maximum) is not int or not 1 <= maximum <= 12:
            raise ValueError("Invalid DZNE detail-request budget")
        root = _xml(await self.http.get_text(_SITEMAP), "urlset", _MAX_SITEMAP)
        locs = [
            (item.findtext("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
             or item.findtext("loc") or "").strip()
            for item in root
            if item.tag.rsplit("}", 1)[-1] == "url"
        ]
        if locs and not any(_vacancy_parts(url) for url in locs):
            raise ValueError("DZNE sitemap has no official individual vacancy identities")
        selected: dict[str, str] = {}
        # Prefer employer English adverts, otherwise retain the German form.
        for url in sorted(locs, key=lambda x: 0 if "/en/jobs/" in x else 1):
            parts = _vacancy_parts(url)
            if parts and _candidate(url):
                selected.setdefault(parts[1], url)
        if not selected:
            self.verified_empty_evidence = True
            return []
        if len(selected) > maximum:
            self.discovery_limits.append("DZNE PhD vacancy detail cap reached")
        results: list[Any] = []
        for url in list(selected.values())[:maximum]:
            try:
                detail = await self.http.get_text(url)
            except Exception as exc:
                self.discovery_fetch_errors.append(type(exc).__name__)
                continue
            results.append((url, detail))
        if not results:
            raise ValueError("DZNE sitemap returned doctoral vacancies but no details were fetched")
        return results

    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        posts: list[JobPostSchema] = []
        for url, data in raw_data:
            try:
                if not isinstance(data, str):
                    raise ValueError("Invalid DZNE detail response")
                root = _xml(data, "jobPublication", _MAX_DETAIL)
                parts = _vacancy_parts(url)
                published_url = _field(root, "jobPublicationURL")
                published = _vacancy_parts(published_url)
                if (
                    parts is None or published is None
                    or published_url != url or published[1] != parts[1]
                    or _field(root, "id") != parts[1]
                    or _field(root, "language") != parts[0]
                ):
                    raise ValueError("DZNE vacancy identity mismatch")
                title = _field(root, "position")
                application = _field(root, "applicationFormURL")
                if (
                    not title or len(title) > 500
                    or not _ROLE.search(title) or _EXCLUDE.search(title.lower().replace(" ", "-"))
                    or application != f"https://jobs.dzne.de/{parts[0]}/jobs/{parts[1]}/apply"
                ):
                    raise ValueError("DZNE vacancy title/application form invalid")
                closing = parse_iso_datetime(_field(root, "endDate"))
                posted = parse_iso_datetime(_field(root, "startDate"))
                if closing is None or posted is None:
                    raise ValueError("DZNE lacks an advertised application interval")
                if closing < datetime.now(UTC).date():
                    continue
                description = " ".join(
                    html_to_text(_field(root, label), max_chars=2400)
                    for label in ("tasks", "profile", "weOffer")
                )
                if not description.strip():
                    raise ValueError("DZNE has no individual research/degree description")
                # Explicit employer workplace wording; don't infer location
                # from collaborating groups or a national institution name.
                city = re.search(r"\b(?:at|in)\s+DZNE\s+(Magdeburg|Bonn|Berlin|"
                                 r"Dresden|Göttingen|Greifswald|München|Rostock|"
                                 r"Tübingen|Witten|Ulm)\b", description, re.I)
                posts.append(self.make(
                    title=title, url=url,
                    date_posted=posted, deadline=closing,
                    deadline_text=f"Employer application closes {closing.isoformat()}",
                    description_snippet=truncate(description, 4300),
                    location=f"{city.group(1)}, Germany" if city else None,
                    extra={"dvinci_req_id": parts[1], "application_form_url": application},
                ))
            except (ValueError, TypeError, OverflowError) as exc:
                self.discovery_parse_errors.append(
                    "Invalid DZNE vacancy detail/identity: " + str(exc)[:100]
                )
        return posts

    async def fetch_detail(self, post: JobPostSchema) -> str | None:
        # Full official jobPublication XML has already been inspected. No
        # second request to the employer is necessary.
        return None
