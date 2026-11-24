"""Reviewed employer indexes with vacancy-scoped detail evidence.

These small public indexes expose stable HTML cards. They are deliberately not
generic site crawlers: every profile pins its listing, job identity, and advert
container. A school name or a careers navigation link is never an advert.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

from ..config import SourceConfig
from ..http import FetchError, HttpClient
from ..models import JobPostSchema
from ..utils.dates import extract_deadline, today
from ..utils.geo import detect_location
from ..utils.text import clean_ws, html_to_text, normalize_title, truncate
from .base import BaseScraper, register

_PROFILES = {
    "esmt": {
        "url": "https://jobs.esmt.berlin/de",
        "host": "jobs.esmt.berlin",
        "heading": "Jobs @ ESMT Berlin",
        "cards": ".portlet.light.bordered:has(.portlet-title a.job-offer-content)",
        "link": ".portlet-title a.job-offer-content[href]",
        "title": "h2",
    },
    "isb": {
        "url": "https://www.isb.edu/work-at-isb/academic-openings",
        "host": "www.isb.edu",
        "heading": "Academic Openings",
        "cards": "main.inner-page .isb-link-items__cta[href]",
        "link": "",
        "title": ".isb-link-items__listTitle",
    },
    "wu": {
        "url": "https://jobs.wu.ac.at/",
        "host": "jobs.wu.ac.at",
        "heading": "Aktuelle Stellenausschreibungen",
        "cards": "main article.joboffer_container",
        "link": ".joboffer_title_text > a[href]",
        "title": ".joboffer_title_text > a[href]",
    },
}
_WU_JOB = re.compile(r"/[A-Za-z0-9][A-Za-z0-9-]*-(?:eng|de)-j([1-9]\d*)\.html")
_ISB_JOB = re.compile(r"/work-at-isb/academic-openings/([a-z0-9]+(?:-[a-z0-9]+)*)/?")
_WU_TEASER = re.compile(r"(?:ID\s+)?(\d+)\s+(?:[-–]\s*)?(.+)")
_WU_GERMAN_CLOSE_LABEL = re.compile(r"bewerben Sie sich bitte bis spätestens", re.I)
_WU_GERMAN_CLOSE = re.compile(
    r"bewerben Sie sich bitte bis spätestens\s+(\d{2}\.\d{2}\.\d{4})"
    r"\s*\(Kennzahl:\s*(\d+)\)", re.I,
)
_WU_UNIT = re.compile(r"^(?:Institute|Institut|Department)\b", re.I)
_ISB_JOB_SECTIONS = {
    "overview", "about the role", "about this position", "key responsibilities",
    "roles and responsibilities", "roles & responsibilities", "required qualifications",
    "ideal candidate profile", "required qualifications and skills",
    "required skills and qualifications", "preferred experience and skills",
    "job outline", "job specifications",
}
_ISB_START = re.compile(
    r"(?:Start\s+Date\s*:|expected date of joining is)\s*"
    r"([A-Za-z]+\s+\d{1,2},\s+20\d{2})(?!\d)", re.I,
)


def _job_identity(profile: str, url: str) -> str | None:
    """Only the reviewed provider's public, requisition-specific URL shapes."""
    try:
        parts = urlsplit(url)
        if (
            parts.scheme != "https" or parts.hostname != _PROFILES[profile]["host"]
            or parts.username is not None or parts.password is not None
            or parts.port not in (None, 443) or parts.fragment
            or any(char.isspace() for char in url)
        ):
            return None
        if profile == "esmt":
            query = parse_qs(parts.query, keep_blank_values=True)
            ids = query.get("id", [])
            if (
                parts.path in {"/", "/de"} and set(query) == {"id"}
                and len(ids) == 1 and re.fullmatch(r"[a-f0-9]{6}", ids[0])
            ):
                return ids[0]
            return None
        if parts.query:
            return None
        match = (_WU_JOB if profile == "wu" else _ISB_JOB).fullmatch(parts.path)
        return match.group(1) if match else None
    except (KeyError, ValueError):
        return None


def _single(root: BeautifulSoup | Tag, selector: str) -> Tag:
    nodes = root.select(selector)
    if len(nodes) != 1:
        raise ValueError("Official advert layout or identity changed")
    return nodes[0]


def _from_marker(root: Tag, marker: Tag) -> str:
    """Visible text from an explicit department marker, excluding welcome text."""
    started = False
    text = []
    for node in root.descendants:
        if node is marker:
            started = True
        if started and isinstance(node, NavigableString):
            text.append(str(node))
    return clean_ws(" ".join(text))


@register
class OfficialResearchScraper(BaseScraper):
    """A matching main advert is mandatory before new candidates are emitted."""

    type_name = "official_research"
    requires_verified_detail = True

    def __init__(self, cfg: SourceConfig, http: HttpClient):
        super().__init__(cfg, http)
        self._detail_lock = asyncio.Lock()
        self._detail_restricted = False

    def _profile(self) -> str:
        profile = self.opt("site_profile")
        if (
            profile not in _PROFILES
            or self.opt("url") != _PROFILES[profile]["url"]
            or self.opt("urls") or self.cfg.field_implied
        ):
            raise ValueError("Unexpected reviewed official source configuration")
        return str(profile)

    async def fetch_raw_postings(self) -> list[Any]:
        profile = self._profile()
        url = _PROFILES[profile]["url"]
        return [(url, await self.http.get_text(url))]

    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        profile = self._profile()
        spec = _PROFILES[profile]
        if len(raw_data) != 1 or raw_data[0][0] != spec["url"]:
            raise ValueError("Unexpected official listing payload")
        soup = BeautifulSoup(raw_data[0][1], "lxml")
        heading = _single(soup, "h1")
        if clean_ws(heading.get_text(" ")) != spec["heading"]:
            raise ValueError("Official vacancy index heading missing")
        cards = soup.select(spec["cards"])
        if not cards:
            # None of these sites has a reviewed zero-vacancy contract yet.
            raise ValueError("Official vacancy cards missing; emptiness unverified")
        if soup.select('a[rel~="next"], .pagination a[href], .pager a[href]'):
            self.discovery_limits.append("Official index exposes unreviewed pagination")
        if len(cards) > 200:
            self.discovery_limits.append("Official vacancy card limit reached")
        posts: dict[str, JobPostSchema] = {}
        conflicts: set[str] = set()
        for card in cards[:200]:
            try:
                anchor = _single(card, spec["link"]) if spec["link"] else card
                title = clean_ws(_single(card, spec["title"]).get_text(" "))
                href = anchor.get("href")
                if not isinstance(href, str) or not title:
                    raise ValueError("Official vacancy title or link missing")
                url = urljoin(spec["url"], href)
                identity = _job_identity(profile, url)
                if identity is None:
                    raise ValueError("Unexpected official vacancy identity")
                department = None
                if profile == "wu":
                    teaser = clean_ws(_single(card, ".job_teaser").get_text(" "))
                    match = _WU_TEASER.fullmatch(teaser)
                    if match is None or match.group(1) != identity:
                        raise ValueError("Official vacancy teaser identity disagrees")
                    department = match.group(2)
                post = self.make(
                    title=title, url=url, department=department,
                    # Do not carry a whole surrounding school page into field checks.
                    description_snippet=truncate(department or "", 500),
                    extra={"official_requisition_id": identity},
                )
                if identity in posts and posts[identity].title != post.title:
                    conflicts.add(identity)
                    raise ValueError("Conflicting official vacancy titles for one identity")
                posts.setdefault(identity, post)
            except ValueError as exc:
                self.discovery_parse_errors.append(str(exc))
        return [post for identity, post in posts.items() if identity not in conflicts]

    async def fetch_detail(self, post: JobPostSchema) -> str | None:
        profile = self._profile()
        identity = _job_identity(profile, post.url)
        post.extra.pop("official_detail_verified", None)
        post.extra.pop("official_subject_text", None)
        post.extra.pop("official_detail_failure_reason", None)
        post.extra["official_detail_failure_stage"] = "parse"
        if identity is None or identity != post.extra.get("official_requisition_id"):
            raise ValueError("Unexpected official vacancy detail identity")
        # Once one advert is denied, do not probe more jobs from this provider.
        # Serialize within the provider so a queued request sees the refusal.
        async with self._detail_lock:
            post.extra["official_detail_failure_stage"] = "fetch"
            if self._detail_restricted:
                return None
            try:
                response = await self.http.request("GET", post.url)
            except FetchError as exc:
                if exc.status in {403, 429} or str(exc) == "access_interstitial":
                    self._detail_restricted = True
                raise
        post.extra["official_detail_failure_stage"] = "parse"
        final = str(response.url)
        if _job_identity(profile, final) != identity:
            raise ValueError("Official advert redirected to a different vacancy")
        soup = BeautifulSoup(response.text, "lxml")
        if profile in {"esmt", "wu"}:
            canonical = _single(soup, 'link[rel~="canonical"]').get("href")
            if not isinstance(canonical, str) or _job_identity(profile, canonical) != identity:
                raise ValueError("Official advert canonical identity disagrees")
        sections: list[Tag]
        deadline = None
        deadline_text = None
        location = None
        if profile == "esmt":
            root = _single(soup, "div.container:has(.header-picture h1)")
            heading = _single(root, "h1")
            sections = root.select(".description-anchor-color")
            if len(sections) < 3:
                raise ValueError("Official ESMT advert sections missing")
            content = "\n".join(html_to_text(str(node)) for node in sections)
            subject_sections = [
                node for node in sections
                if clean_ws(_single(node, "h2").get_text(" ")).casefold() in {
                    "what makes you a great fit", "how you will make a difference",
                }
            ]
            if len(subject_sections) != 2:
                raise ValueError("Official ESMT duties or qualifications missing")
            subject = "\n".join(html_to_text(str(node)) for node in subject_sections)
        elif profile == "isb":
            root = _single(soup, "main.inner-page")
            heading = _single(root, "h2.isb-tier-banner__title")
            sections = root.select(".isb-richtext__content")
            if not sections:
                raise ValueError("Official ISB advert body missing")
            content = "\n".join(html_to_text(str(node)) for node in sections)
            subject_sections = [
                node for node in sections
                if (h := node.select_one("h2")) is not None
                and clean_ws(h.get_text(" ")).casefold().rstrip(":") in _ISB_JOB_SECTIONS
            ]
            if not subject_sections:
                raise ValueError("Official ISB role or qualification sections missing")
            subject = "\n".join(html_to_text(str(node)) for node in subject_sections)
            locations = {
                clean_ws(node.get_text(" ")).removeprefix("Location:").strip()
                for section in subject_sections for node in section.select("p")
                if clean_ws(node.get_text(" ")).startswith("Location:")
            }
            if len(locations) > 1:
                raise ValueError("Conflicting official ISB advert location labels")
            location = next(iter(locations), None)
        else:
            root = _single(soup, "main #jobTplContainer")
            heading = _single(root, ".scheme-title h1")
            introduction = _single(root, ".scheme-introduction")
            # The welcome paragraph may change wording or tags. Its field words
            # are never evidence: begin at the explicit employer-unit marker.
            unit = _single(introduction, "strong")
            unit_text = clean_ws(unit.get_text(" "))
            if not _WU_UNIT.search(unit_text):
                raise ValueError("Official WU department boundary missing")
            sections = [_single(root, selector) for selector in (
                ".scheme-task", ".scheme-profile", ".scheme-contact",
            )]
            content = _from_marker(introduction, unit) + "\n" + "\n".join(
                html_to_text(str(node)) for node in sections
            )
            # Salary, employee benefits and general school branding have no
            # bearing on whether the actual research subject is in scope.
            subject = unit_text + "\n" + "\n".join(
                html_to_text(str(node)) for node in sections[:2]
            )
            contact = html_to_text(str(sections[-1]))
            labels = _WU_GERMAN_CLOSE_LABEL.findall(contact)
            matches = list(_WU_GERMAN_CLOSE.finditer(contact))
            if labels:
                if len(matches) != len(labels) or any(m.group(2) != identity for m in matches):
                    raise ValueError("WU application deadline identity or full year missing")
                dates = {datetime.strptime(m.group(1), "%d.%m.%Y").date() for m in matches}
                if len(dates) != 1:
                    raise ValueError("Conflicting WU application deadlines")
                deadline = dates.pop()
                deadline_text = matches[0].group(0)
        if normalize_title(heading.get_text(" ")) != normalize_title(post.title):
            raise ValueError("Official advert title differs from its listing")
        if len(clean_ws(content)) < 120:
            raise ValueError("Official advert body is incomplete")
        if not clean_ws(subject):
            raise ValueError("Official advert subject evidence is missing")
        if profile == "isb":
            # ISB is an Indian institution despite its .edu domain. Prefer an
            # explicit advert location; otherwise retain the reviewed India
            # profile instead of replacing it with a US suffix guess.
            country, region = detect_location(location)
            if not region and location and re.search(r"\b(?:Hyderabad|Mohali)\b", location):
                # Both campus names are explicitly located on the reviewed
                # official ISB page; this is the advert's own Location field.
                country, region = "India", "Other"
            post.country, post.region = (country, region) if country and region else ("India", "Other")
            post.location = location
            post.extra.pop("source_country_default", None)
            post.extra["official_country_basis"] = "advert_label" if country and region else "reviewed_isb_profile"
            start_dates = {
                datetime.strptime(clean_ws(match), "%B %d, %Y").date()
                for match in _ISB_START.findall(subject)
            }
            close, _ = extract_deadline(content)
            if (any(start < today() - timedelta(days=30) for start in start_dates)
                    and not (close and close >= today())):
                # A past start is not proof of closure. Defer these stale
                # adverts until their publisher supplies current evidence.
                post.extra["official_detail_failure_reason"] = "past_start_unconfirmed"
                raise ValueError("Official advert has an elapsed start; current recruitment unconfirmed")
        if deadline is not None:
            post.deadline, post.deadline_text = deadline, deadline_text
        post.extra["final_url"] = final
        post.extra["official_detail_verified"] = True
        post.extra["official_subject_text"] = subject
        post.extra.pop("official_detail_failure_stage", None)
        return clean_ws(heading.get_text(" ")) + "\n" + content
