"""Read official ETH careers JSON using the center's embedded organization IDs.

ETH's jobs page is a JavaScript widget; the HTML does not contain vacancy
anchors. The JSON endpoint includes all ETH departments, so never publish it
without applying the law-and-economics page's own organizational filter.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from ..models import JobPostSchema
from ..utils.dates import parse_date
from ..utils.text import html_to_text, truncate
from .base import BaseScraper, register

_PAGE = "https://lawecon.ethz.ch/group/open-positions.html"
_FEED_PATH = "/group/open-positions/_jcr_content/par/jobs.softfactors.json"
_FEED = "https://lawecon.ethz.ch" + _FEED_PATH
_ORGS = re.compile(r"\d{5}(?:,\d{5})*")
_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
_JOB_PATH = re.compile(r"/job/(?:en|de)/\d+/?$")


def _official_job_url(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = urlsplit(value)
        params = parse_qs(parsed.query, keep_blank_values=True)
        return (
            parsed.scheme == "https"
            and parsed.hostname in {"jobs.ethz.ch", "www.jobs.ethz.ch"}
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and not parsed.fragment
            and bool(_JOB_PATH.fullmatch(parsed.path))
            and (not params or params == {"mw_source": ["jobs_ethz"]})
        )
    except ValueError:
        return False


def _english_text(mapping: object) -> str | None:
    if not isinstance(mapping, dict):
        return None
    for key in ("en", "de"):
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


@register
class EthSoftfactorsScraper(BaseScraper):
    """Retrieve ETH Law & Economics vacancies, excluding unrelated ETH faculties."""

    type_name = "eth_softfactors"

    async def fetch_raw_postings(self) -> list[Any]:
        page = self.opt("url")
        if page != _PAGE:
            raise ValueError("Unexpected ETH Law & Economics source URL")
        html = await self.http.get_text(page)
        soup = BeautifulSoup(html, "lxml")
        portals = soup.select('.job-portal[data-init="jobs"]')
        if len(portals) != 1:
            self.discovery_parse_errors.append("ETH official vacancy widget missing")
            return []
        portal = portals[0]
        path, org_raw = portal.get("data-url"), portal.get("data-orgs")
        if (
            path != _FEED_PATH
            or not isinstance(org_raw, str)
            or _ORGS.fullmatch(org_raw) is None
        ):
            self.discovery_parse_errors.append("ETH vacancy widget feed or unit IDs changed")
            return []
        data = await self.http.get_json(_FEED)
        if not isinstance(data, list):
            self.discovery_parse_errors.append("Invalid ETH official vacancy JSON array")
            return []
        return [(frozenset(org_raw.split(",")), data)]

    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        posts: list[JobPostSchema] = []
        for orgs, records in raw_data:
            for entry in records:
                if not isinstance(entry, dict):
                    self.discovery_parse_errors.append("Invalid ETH vacancy object")
                    continue
                characterization = entry.get("characterization")
                if not isinstance(characterization, dict):
                    self.discovery_parse_errors.append("Invalid ETH vacancy organization")
                    continue
                if str(characterization.get("internalClassification")) not in orgs:
                    continue
                desc, pub = entry.get("description"), entry.get("publication")
                ident = entry.get("id")
                if (
                    not isinstance(desc, dict)
                    or not isinstance(pub, dict)
                    or not isinstance(ident, str)
                    or not _ID.fullmatch(ident)
                ):
                    self.discovery_parse_errors.append("Invalid ETH vacancy identity")
                    continue
                title = _english_text(desc.get("title"))
                url = pub.get("jobboardDetailUrl_en") or pub.get("jobboardDetailUrl_de")
                if not title or not _official_job_url(url):
                    self.discovery_parse_errors.append("Invalid ETH vacancy title or URL")
                    continue
                intro = _english_text(desc.get("eth_intro"))
                content = entry.get("content")
                if not intro and isinstance(content, dict):
                    intro = _english_text(content)
                description = truncate(html_to_text(intro), 500) if intro else ""
                posted = pub.get("publicationDate")
                if posted is not None and not isinstance(posted, str):
                    self.discovery_parse_errors.append("Invalid ETH publication date")
                    continue
                try:
                    posts.append(self.make(
                        title=title,
                        url=url,
                        department=_english_text(desc.get("eth_area")),
                        date_posted=parse_date(posted),
                        deadline=None,
                        description_snippet=description,
                        extra={"eth_job_id": ident},
                    ))
                except (TypeError, ValueError):
                    self.discovery_parse_errors.append("Unparseable ETH vacancy")
        return posts
