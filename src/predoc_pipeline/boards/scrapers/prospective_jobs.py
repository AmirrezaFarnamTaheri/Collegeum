"""University of Bern's official read-only Prospective recruitment API.

The HTML career index embeds a JavaScript-only Prospective iframe and has
no static vacancy anchors. Its published browser bundle uses the public
`/public/v1/medium/1001892/jobs` endpoint. Read-only runner
#41190504560 validated a 62-row index, real employer-hosted directlinks,
UUID identities, location metadata, and publication/deadline timestamps.

Only the exact university feed is accepted. The source health must record
pagination, malformed vacancy metadata, or outages as partial/failed rather
than declaring an empty hiring season.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from ..models import JobPostSchema
from ..utils.dates import extract_deadline, parse_date, parse_iso_datetime
from ..utils.text import clean_ws, html_to_text
from .base import BaseScraper, register

_LANDING = "https://karriere.unibe.ch/offene_stellen/index_ger.html"
_API = "https://ohws.prospective.ch/public/v1/medium/1001892/jobs"
_ID = re.compile(r"[1-9]\d{1,15}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\Z", re.I
)
_PATH = re.compile(
    r"/(?:job-vacancies|offene-stellen)/[a-z0-9-]+/"
    r"([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})/?\Z", re.I
)
_PAGE_SIZE = 12
_MAX_PAGES = 8  # 96 index jobs per source; record a partial limit if more.
_ROLLING_APPLICATION = re.compile(
    r"\brolling\b|\buntil\s+(?:the\s+)?(?:position|role|post|job)\s+(?:is\s+)?filled\b"
    r"|\buntil\s+filled\b", re.I,
)

# A few employer adverts say "submit your application including ... by DATE".
# The generic extractor intentionally doesn't scan arbitrary intervening text;
# this bounded pattern is restricted to UniBE's application-instructions field.
_SUBMIT_BY_DATE = re.compile(
    r"\\b(?:submit(?:ted)?|send|email)\\b.{0,230}?\\bby\\s+"
    r"(?P<date>20\\d{2}-\\d{1,2}-\\d{1,2}|"
    r"\\d{1,2}[./-]\\d{1,2}[./-]20\\d{2}|"
    r"\\d{1,2}\\s+[A-Za-z]+\\s+20\\d{2})\\b",
    re.I | re.S,
)


def _employer_application_cutoff(text: str) -> date | None:
    # Review/start dates and administrative index dates are not hard cutoffs.
    explicit, _ = extract_deadline(text)
    if explicit is not None:
        return explicit
    submission = _SUBMIT_BY_DATE.search(text)
    return parse_date(submission.group("date")) if submission else None


def _official_url(value: object, viewkey: str) -> bool:
    """Require an exact UniBE vacancy permalink tied to the API viewkey."""
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        return False
    try:
        url = urlsplit(value)
        path = _PATH.fullmatch(url.path)
        return bool(
            url.scheme == "https"
            and url.hostname == "jobs.unibe.ch"
            and url.username is None
            and url.password is None
            and url.port in (None, 443)
            and not url.query
            and not url.fragment
            and path is not None
            and path.group(1).lower() == viewkey.lower()
        )
    except ValueError:
        return False


def _workplace(szas: dict[str, Any]) -> str | None:
    city = szas.get("sza_location.city")
    raw_country = szas.get("sza_location.country")
    if isinstance(city, str):
        city = clean_ws(city)[:100]
    else:
        city = ""
    country = raw_country if isinstance(raw_country, str) else ""
    country = {
        "schweiz": "Switzerland", "suisse": "Switzerland",
        "svizzera": "Switzerland",
    }.get(country.casefold().strip(), country)
    country = clean_ws(country)[:60]
    return ", ".join(p for p in (city, country) if p) or None


def _department(attributes: dict[str, Any]) -> str | None:
    for key, values in attributes.items():
        if (
            key.startswith("70_")
            and isinstance(values, list)
            and len(values) == 1
            and isinstance(values[0], str)
            and values[0].strip()
        ):
            return clean_ws(values[0])[:160]
    return None


@register
class ProspectiveJobsScraper(BaseScraper):
    """Bounded, official employer API; no browser, third-party sites or writes."""

    type_name = "prospective_jobs"

    async def fetch_raw_postings(self) -> list[Any]:
        if (
            self.name != "life_dach_bern"
            or self.opt("url") != _LANDING
            or self.opt("api_url") != _API
        ):
            raise ValueError("Unexpected University of Bern public API configuration")
        pages = int(self.opt("max_pages", _MAX_PAGES))
        if not 1 <= pages <= _MAX_PAGES:
            raise ValueError("Bern Prospective page limit must be 1..8")

        offset = 0
        rows: list[Any] = []
        total: int | None = None
        seen: set[str] = set()
        self.verified_empty_evidence = False
        for _ in range(pages):
            url = f"{_API}?offset={offset}&limit={_PAGE_SIZE}&lang=en"
            try:
                data = await self.http.get_json(url)
            except Exception as exc:  # noqa: BLE001 - keep valid previous pages
                if not rows:
                    raise
                self.discovery_fetch_errors.append(type(exc).__name__)
                break
            if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
                self.discovery_parse_errors.append("Invalid UniBE jobs API response")
                break
            count = data.get("total")
            if (
                type(data.get("offset")) is not int
                or data["offset"] != offset
                or type(count) is not int
                or count < 0
                or (total is not None and count != total)
            ):
                self.discovery_parse_errors.append("Inconsistent UniBE pagination metadata")
                break
            if total is None:
                total = count
            batch = data["jobs"]
            if len(batch) > _PAGE_SIZE or offset + len(batch) > total:
                self.discovery_parse_errors.append("UniBE jobs count exceeds reported total")
                break
            identities = []
            for item in batch:
                if isinstance(item, dict) and isinstance(item.get("viewkey"), str):
                    identities.append(item["viewkey"].casefold())
            if any(x in seen for x in identities) or len(set(identities)) != len(identities):
                self.discovery_parse_errors.append("UniBE job list repeats a page or identity")
                break
            seen.update(identities)
            rows.extend(batch)
            offset += len(batch)
            if offset >= total:
                self.verified_empty_evidence = bool(
                    not rows and total == 0
                    and not self.discovery_fetch_errors
                    and not self.discovery_parse_errors
                )
                break
            if len(batch) < _PAGE_SIZE:
                self.discovery_parse_errors.append("UniBE API returned incomplete page")
                break
        else:
            if total is None or offset < total:
                self.discovery_limits.append("UniBE jobs pagination cap reached")
        return rows

    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        posts: list[JobPostSchema] = []
        for item in raw_data:
            if not isinstance(item, dict):
                self.discovery_parse_errors.append("Invalid UniBE vacancy object")
                continue
            ident, viewkey = item.get("id"), item.get("viewkey")
            title, links = item.get("title"), item.get("links")
            if (
                not isinstance(ident, str)
                or _ID.fullmatch(ident) is None
                or not isinstance(viewkey, str)
                or _UUID.fullmatch(viewkey) is None
                or not isinstance(title, str)
                or not clean_ws(title)
                or not isinstance(links, dict)
                or not _official_url(links.get("directlink"), viewkey)
            ):
                self.discovery_parse_errors.append("Invalid UniBE vacancy identity or link")
                continue
            szas, attributes = item.get("szas"), item.get("attributes")
            if not isinstance(szas, dict) or not isinstance(attributes, dict):
                self.discovery_parse_errors.append("Invalid UniBE vacancy attributes")
                continue
            started, closes = item.get("start_date"), item.get("end_date")
            if (
                (started is not None and not isinstance(started, str))
                or (closes is not None and not isinstance(closes, str))
            ):
                self.discovery_parse_errors.append("Invalid UniBE vacancy dates")
                continue
            texts = [
                html_to_text(szas.get(key, ""))
                for key in (
                    "sza_tasks", "sza_requirements",
                    "sza_application", "sza_introduction",
                )
                if isinstance(szas.get(key), str)
            ]
            description = clean_ws(" \n ".join(texts))[:4200]
            posted = parse_iso_datetime(started)
            close_date = parse_iso_datetime(closes)
            # Prospective may use a decade-long administrative end_date for
            # rolling or unspecified recruitment. This is NOT proof of an
            # application cutoff. The classifier already rejects deadlines
            # more than three years away; preserve the same fail-closed bound
            # during extraction so downstream metadata is not misleading.
            application_raw = szas.get("sza_application")
            application_text = (
                html_to_text(application_raw)
                if isinstance(application_raw, str) else ""
            )
            employer_cutoff = _employer_application_cutoff(application_text)
            long_horizon = bool(
                posted is not None
                and close_date is not None
                and (close_date - posted).days > 366 * 3
            )
            rolling_application = bool(
                _ROLLING_APPLICATION.search(application_text)
                or (long_horizon and _ROLLING_APPLICATION.search(description))
            )
            # Even a near-term Prospective end_date is only an index date
            # until the employer explicitly corroborates a hard cutoff.
            # Preserve discovery; do not manufacture publication eligibility.
            unverified_end = bool(
                close_date is not None
                and (
                    long_horizon or rolling_application
                    or employer_cutoff != close_date
                )
            )
            deadline_note: str | None
            if unverified_end:
                deadline = None
                deadline_note = (
                    "Rolling until filled" if rolling_application
                    else "Unverified employer-index end date"
                )
            else:
                deadline = close_date
                deadline_note = (
                    f"Official UniBE posting ends {closes}" if closes else None
                )
            provenance: dict[str, Any] = {
                "prospective_id": ident,
                "prospective_viewkey": viewkey,
                "prospective_full_text": description,
            }
            if unverified_end:
                # The raw provider value remains auditable, but never becomes
                # a verified deadline or accidentally passes a loose caller.
                provenance["prospective_unverified_end_date"] = closes
                provenance["require_deadline"] = True
            try:
                posts.append(self.make(
                    title=title,
                    url=links["directlink"],
                    location=_workplace(szas),
                    department=_department(attributes),
                    date_posted=posted,
                    deadline=deadline,
                    deadline_text=deadline_note,
                    description_snippet=description,
                    extra=provenance,
                ))
            except (TypeError, ValueError, OverflowError):
                self.discovery_parse_errors.append("Unparseable UniBE vacancy")
        return posts

    async def fetch_detail(self, post: JobPostSchema) -> str | None:
        # The published jobs API already supplies role description and
        # requirements; avoid re-fetching a JavaScript-heavy job page.
        return post.extra.get("prospective_full_text") or None
