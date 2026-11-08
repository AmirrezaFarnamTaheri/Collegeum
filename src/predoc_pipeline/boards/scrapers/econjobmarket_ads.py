"""Opt-in EJM JSON advertisement adapter; requires redistribution approval.

EconJobMarket publishes a JSON feed, but requires operators redisplaying ads
to notify the provider and obtain approval. This adapter cannot access that
feed until the source config explicitly records that approval. It never
requires applicant/recruiter credentials, and never changes existing notices.
"""
from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlsplit

from ..models import JobPostSchema
from ..utils.text import clean_ws, html_to_text, truncate
from .base import BaseScraper, SourceSkipped, register

_PUBLIC_ADS = "https://backend.econjobmarket.org/data/zz_public/json/Ads"
_JOB_PATH = re.compile(r"/positions/[1-9][0-9]{1,8}/?")


def _ad_url(value: Any) -> bool:
    if not isinstance(value, str) or any(char.isspace() for char in value):
        return False
    try:
        parts = urlsplit(value)
        return (
            parts.scheme == "https"
            and parts.hostname == "econjobmarket.org"
            and parts.username is None
            and parts.password is None
            and parts.port in (None, 443)
            and not parts.query
            and not parts.fragment
            and _JOB_PATH.fullmatch(parts.path) is not None
        )
    except ValueError:
        return False


def _iso_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("date is not a string")
    return date.fromisoformat(value)


def _names(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return clean_ws(", ".join(
        entry["name"] for entry in value
        if isinstance(entry, dict)
        and isinstance(entry.get("name"), str)
        and entry["name"].strip()
    ))[:300]


@register
class EconJobMarketAdsScraper(BaseScraper):
    """Read only the provider's documented public ad-redisplay endpoint."""

    type_name = "econjobmarket_ads"

    async def fetch_raw_postings(self) -> list[Any]:
        # An empty or typoed approval flag never contacts the provider.
        if self.opt("redistribution_approved") is not True:
            raise SourceSkipped("EJM advertisement redisplay approval not configured")
        if self.urls() != [_PUBLIC_ADS]:
            raise ValueError("Unexpected EJM public advertisement endpoint")
        return await self.http.get_json(
            _PUBLIC_ADS,
            headers={"Accept": "application/json"},
            stop_on_429=True,
        )

    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        if not isinstance(raw_data, list) or not raw_data:
            self.discovery_parse_errors.append("EJM public ads array is missing or empty")
            return []
        if len(raw_data) > 2000:
            self.discovery_limits.append("EJM public ads result exceeds safe cap")
            raw_data = raw_data[:2000]

        results: list[JobPostSchema] = []
        for entry in raw_data:
            if not isinstance(entry, dict):
                self.discovery_parse_errors.append("EJM ad is not an object")
                continue
            title = entry.get("adtitle")
            name = entry.get("name")
            url = entry.get("url")
            if not (
                isinstance(title, str) and title.strip()
                and isinstance(name, str) and name.strip()
                and _ad_url(url)
            ):
                self.discovery_parse_errors.append("EJM ad has invalid title, employer or URL")
                continue
            try:
                posted = _iso_date(entry.get("startdate"))
                deadline = _iso_date(entry.get("deadline_date"))
                end = _iso_date(entry.get("enddate"))
            except ValueError:
                self.discovery_parse_errors.append("EJM ad has invalid date metadata")
                continue
            if end is not None and end < datetime.now(UTC).date():
                continue  # The provider has explicitly ended display of this ad.
            adtext = entry.get("adtext")
            if adtext is not None and not isinstance(adtext, str):
                self.discovery_parse_errors.append("EJM ad description is malformed")
                continue
            try:
                post = self.make(
                    title=title,
                    url=url,
                    institution=name,
                    department=entry.get("department")
                    if isinstance(entry.get("department"), str) else None,
                    fields_of_research=_names(entry.get("categories")) or None,
                    date_posted=posted,
                    deadline=deadline,
                    deadline_text=f"Application deadline {deadline.isoformat()}"
                    if deadline else None,
                    description_snippet=truncate(html_to_text(adtext or ""), 500),
                )
            except (TypeError, ValueError):
                self.discovery_parse_errors.append("EJM ad has unusable typed fields")
                continue
            results.append(post)
        if not results and not self.discovery_parse_errors:
            self.discovery_parse_errors.append("EJM feed had no usable open ads")
        return results
