"""Reviewed public university vacancy indexes and matching advert bodies.

Each profile pins its origin, pagination and advert layout. Research-role cards
still need subject evidence from duties or qualifications; university navigation,
employee benefits and general faculty biographies never supply that evidence.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime
from typing import Any, TypedDict
from urllib.parse import parse_qs, urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

from ..config import SourceConfig
from ..http import FetchError, HttpClient
from ..models import JobPostSchema
from ..utils.dates import extract_deadline
from ..utils.geo import detect_location
from ..utils.text import clean_ws, html_to_text, normalize_title
from .base import BaseScraper, register

_UU_PATH = "/en/organisation/working-at-utrecht-university/jobs"


class _Profile(TypedDict):
    host: str
    paths: dict[str, str]
    cards: str


_PROFILES: dict[str, _Profile] = {
    "vienna": {
        "host": "jobs.univie.ac.at",
        "paths": {"/go/Praedoc/8877001/": "Praedoc", "/go/Postdoc/8879501/": "Postdoc"},
        "cards": "tr.data-row",
    },
    "maastricht": {
        "host": "vacancies.maastrichtuniversity.nl",
        "paths": {"/go/All-jobs/8842002/": "All jobs"},
        "cards": "tr.data-row",
    },
    "amsterdam": {
        "host": "werkenbij.uva.nl",
        "paths": {"/en/vacancies": "Explore the possibilities at the UvA"},
        "cards": "a.vacancy-item",
    },
    "utrecht": {
        "host": "www.uu.nl", "paths": {_UU_PATH: "Jobs"},
        "cards": "li.overview-list__item .vacancy",
    },
}
_ROLE = re.compile(
    r"\b(?:pre[- ]?doc\w*|prae[- ]?doc\w*|post[- ]?doc\w*|ph[.]?d[.]?s?\b|"
    r"research (?:assistant|associate|fellow|position)\b|researcher\b|promovend\w*)", re.I,
)
_VIENNA_ENGLISH = re.compile(r"^(?:University|Scientific|Research|PhD|Predoctoral|Postdoctoral)\b", re.I)
_VIENNA_SECTIONS = {
    "your personal sphere of influence", "your personal sphere of play",
    "your future tasks", "this is part of your personality",
    "your opportunities in this role", "your specific responsibilities",
    "your qualifications and personal qualities",
    "research context", "job description", "required qualifications",
}
_MAASTRICHT_SECTIONS = {"what you do", "what you bring", "wat jij doet", "wat jij meebrengt"}
_AMSTERDAM_DUTIES = {"what you will do", "this is what you will do", "what are you going to do", "this is what you are going to do"}
_AMSTERDAM_QUALIFICATIONS = {"what we ask of you", "this is what we ask of you", "what do you have to offer"}
_DETAIL_CLOSE = re.compile(
    r"\b(?:application\s+deadline|deadline|closing\s+date|"
    r"apply\s+(?:by|before|(?:for this position,?\s+)?no\s+later\s+than)|"
    r"applications?\s+(?:close|are\s+due)|(?:the )?end date of the publication is|"
    r"de einddatum van de publicatie is|sluitingsdatum)\b\s*:?\s*", re.I,
)
_NEXT_DATE_FIELD = re.compile(
    r"\b(?:de (?:eerste )?gesprekken|interviews?|preferred starting date|start(?:ing)? date)\b", re.I,
)
_UNCERTAIN_CUTOFF = re.compile(
    r"\b(?:TBD|TBA|to be (?:announced|confirmed)|unknown|"
    r"(?:international|domestic|local|overseas|EU|non-EU)\s+(?:applicants?|candidates?))\b", re.I,
)
_EARLY_FILL_NOTICE = re.compile(
    r"The selection process will start immediately and may close before the application "
    r"deadline if a suitable candidate is identified\.", re.I,
)
_MAX_PAGES = 8
_MAX_CARDS = 250


def _one(root: BeautifulSoup | Tag, selector: str) -> Tag:
    matches = root.select(selector)
    if len(matches) != 1:
        raise ValueError("Official university advert layout or identity changed")
    return matches[0]


def _text(node: Tag) -> str:
    return clean_ws(node.get_text(" "))


def _origin(profile: str, url: str) -> bool:
    try:
        parts = urlsplit(url)
        return bool(
            parts.scheme == "https" and parts.hostname == _PROFILES[profile]["host"]
            and parts.port in (None, 443) and parts.username is None and parts.password is None
            and not parts.fragment and not re.search(r"[\s\\]|%(?:2f|5c|00)", url, re.I)
        )
    except (ValueError, KeyError):
        return False


def _identity(profile: str, url: str) -> str | None:
    if not _origin(profile, url):
        return None
    parts = urlsplit(url)
    if parts.query:
        return None
    if profile in {"vienna", "maastricht"}:
        match = re.fullmatch(r"/job/[^/]+/([1-9]\d{8,11})/?", parts.path)
    elif profile == "amsterdam":
        match = re.fullmatch(r"/en/vacancies/[a-z0-9-]+-([1-9]\d{3,7})", parts.path)
    else:
        match = re.fullmatch(re.escape(_UU_PATH) + r"/([a-z0-9]+(?:-[a-z0-9]+)*)", parts.path)
    return match.group(1) if match else None


def _listing_key(profile: str, url: str) -> tuple[str, int] | None:
    """Only observed, bounded numeric pagination; never follow arbitrary links."""
    if not _origin(profile, url):
        return None
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    paths = _PROFILES[profile]["paths"]
    if profile == "amsterdam":
        if parts.path not in paths or set(query) - {"o"}:
            return None
        offset = query.get("o", ["0"])
        if len(offset) != 1 or not re.fullmatch(r"0|[1-9]\d{0,2}", offset[0]):
            return None
        value = int(offset[0])
        return (parts.path, value) if value % 10 == 0 and value < 250 else None
    if profile == "utrecht":
        return (parts.path, 0) if parts.path in paths and not query else None
    if query and query != {"q": [""], "sortColumn": ["referencedate"], "sortDirection": ["desc"]}:
        return None
    for path in paths:
        if parts.path == path:
            return path, 0
        match = re.fullmatch(re.escape(path) + r"([1-9]\d{0,2})/", parts.path)
        if match and int(match.group(1)) % 25 == 0 and int(match.group(1)) < 250:
            return path, int(match.group(1))
    return None


def _date(value: str, fmt: str) -> date:
    # strptime alone accepts loosely padded input. Full-year scalar syntax is
    # separately required so applicant qualifiers cannot hide another cutoff.
    value = clean_ws(value)
    patterns = {
        "%d-%m-%Y": r"\d{1,2}-\d{1,2}-20\d{2}",
        "%m/%d/%Y": r"\d{1,2}/\d{1,2}/20\d{2}",
        "%d %B %Y": r"\d{1,2} [A-Za-z]+ 20\d{2}",
    }
    if not re.fullmatch(patterns[fmt], value):
        raise ValueError("Official closing date is incomplete or qualified")
    return datetime.strptime(value, fmt).date()


def _time_date(node: Tag, *, numeric: bool = False) -> date:
    visible = _date(_text(node), "%d-%m-%Y" if numeric else "%d %B %Y")
    machine = node.get("data-utc" if numeric else "datetime")
    if not isinstance(machine, str) or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}T[0-9:]+Z?", machine):
        raise ValueError("Official closing-date metadata missing")
    if datetime.fromisoformat(machine.replace("Z", "+00:00")).date() != visible:
        raise ValueError("Official closing dates disagree")
    return visible


def _definition(root: Tag, label: str) -> Tag:
    labels = [node for node in root.select("dt") if _text(node).rstrip(":").casefold() == label]
    if len(labels) != 1 or not isinstance(value := labels[0].find_next_sibling(), Tag) or value.name != "dd":
        raise ValueError("Official vacancy metadata missing or duplicated")
    return value


def _section_text(root: Tag, allowed: set[str], *, bold: bool = False) -> str:
    """Collect every explicit job section, ending at the next peer heading.

Ignore empty layout headings. Bold headings are used only by Maastricht's
reviewed template, and must begin a paragraph rather than emphasize a list item.
"""
    active = False
    found = set()
    text = []
    for node in root.descendants:
        if isinstance(node, Tag):
            heading = node.name in {"h1", "h2", "h3", "h4", "h5", "h6"}
            if bold and node.name in {"strong", "b"} and isinstance(node.parent, Tag) and node.parent.name == "p":
                preceding = "".join(str(x) if isinstance(x, NavigableString) else x.get_text() for x in node.previous_siblings)
                heading = not clean_ws(preceding)
            if heading and (label := _text(node).strip(" :\u200b").casefold()):
                active = label in allowed
                if active:
                    found.add(label)
        elif isinstance(node, NavigableString) and active and node.parent is not None and node.parent.name not in {"style", "script"}:
            text.append(str(node))
    result = clean_ws(" ".join(text))
    if not found or len(result) < 80:
        raise ValueError("Official job duties or qualifications missing")
    return result


def _job_schema(soup: BeautifulSoup) -> dict[str, Any]:
    objects = []
    for node in soup.select('script[type="application/ld+json"]'):
        obj = json.loads(node.get_text())
        if isinstance(obj, dict) and obj.get("@type") == "JobPosting":
            objects.append(obj)
    if len(objects) != 1:
        raise ValueError("Official structured vacancy identity missing")
    return objects[0]


def _consistent_detail_cutoffs(root: Tag, deadline: date | None) -> None:
    """Every explicit cutoff must agree, including incomplete alternate fields.

    Paragraph boundaries keep ordinary 'close collaboration' and benefits out of
    deadline parsing. Count labels in the complete advert too: moving a second
    deadline outside the reviewed paragraph layout must not make it disappear.
    """
    # This reviewed sentence references the index cutoff and possible early
    # filling; it does not declare an additional or unknown application date.
    expected = len(list(_DETAIL_CLOSE.finditer(_EARLY_FILL_NOTICE.sub("", html_to_text(str(root))))))
    observed = 0
    for block in root.select("p, li"):
        if block.select("p, li"):
            continue
        text = _EARLY_FILL_NOTICE.sub("", _text(block))
        labels = list(_DETAIL_CLOSE.finditer(text))
        observed += len(labels)
        for index, label in enumerate(labels):
            end = labels[index + 1].start() if index + 1 < len(labels) else len(text)
            field = text[label.end():end]
            field = _NEXT_DATE_FIELD.split(field, maxsplit=1)[0]
            value, _ = extract_deadline("Application deadline: " + field)
            if value is None or value != deadline or _UNCERTAIN_CUTOFF.search(field):
                raise ValueError("Official Maastricht closing date missing or conflicting")
    if observed != expected:
        raise ValueError("Official Maastricht closing-date layout changed")


@register
class OfficialUniversityScraper(BaseScraper):
    """Bounded university listings with mandatory matching advert evidence."""

    type_name = "official_university"
    requires_verified_detail = True

    def __init__(self, cfg: SourceConfig, http: HttpClient):
        super().__init__(cfg, http)
        self._detail_lock = asyncio.Lock()
        self._detail_restricted = False

    def _profile(self) -> str:
        profile = self.opt("site_profile")
        if profile not in _PROFILES or self.cfg.field_implied:
            raise ValueError("Unexpected official university configuration")
        spec = _PROFILES[profile]
        expected = [f"https://{spec['host']}{path}" for path in spec["paths"]]
        if self.urls() != expected:
            raise ValueError("Unexpected official university index URL")
        return str(profile)

    def _listing(self, profile: str, url: str, html: str) -> BeautifulSoup:
        key = _listing_key(profile, url)
        soup = BeautifulSoup(html, "lxml")
        if key is None or _text(_one(soup, "h1")) != _PROFILES[profile]["paths"][key[0]]:
            raise ValueError("Official university listing identity missing")
        if not soup.select(_PROFILES[profile]["cards"]):
            raise ValueError("Official vacancy cards missing; emptiness unverified")
        if profile == "maastricht" and _text(_one(soup, "#hdrShifttype")) != "Closing date":
            raise ValueError("Official closing-date column changed")
        return soup

    async def fetch_raw_postings(self) -> list[Any]:
        profile = self._profile()
        queue = list(self.urls())
        seen: set[tuple[str, int]] = set()
        result: list[Any] = []
        while queue and len(seen) < _MAX_PAGES:
            url = queue.pop(0)
            key = _listing_key(profile, url)
            if key is None or key in seen:
                continue
            seen.add(key)
            try:
                html = await self.http.get_text(url)
                soup = self._listing(profile, url, html)
            except Exception as exc:
                if isinstance(exc, FetchError) and (
                    exc.status in {403, 429} or str(exc) == "access_interstitial"
                ):
                    self._detail_restricted = True
                if not result:
                    raise
                self.discovery_fetch_errors.append(type(exc).__name__)
                break
            result.append((url, html))
            for anchor in soup.select(".pagination a[href]"):
                target = urldefrag(urljoin(url, str(anchor["href"])))[0]
                next_key = _listing_key(profile, target)
                if next_key is None:
                    self.discovery_limits.append("Official index exposes unreviewed pagination")
                elif next_key not in seen and target not in queue:
                    queue.append(target)
        if queue:
            self.discovery_limits.append("Official university page limit reached")
        return result

    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        profile = self._profile()
        if not raw_data or len(raw_data) > _MAX_PAGES:
            raise ValueError("Unexpected official university listing payload")
        posts: dict[str, JobPostSchema] = {}
        conflicts: set[str] = set()
        count = 0
        for url, html in raw_data:
            soup = self._listing(profile, url, html)
            for card in soup.select(_PROFILES[profile]["cards"]):
                count += 1
                if count > _MAX_CARDS:
                    self.discovery_limits.append("Official university card limit reached")
                    break
                try:
                    if profile in {"vienna", "maastricht"}:
                        anchor = _one(card, "span.jobTitle.hidden-phone a.jobTitle-link")
                        title = _text(anchor)
                        department = _text(_one(card, "td.colFacility .jobFacility"))
                    elif profile == "amsterdam":
                        anchor = card
                        title = _text(_one(card, "h3"))
                        department = _text(_one(card, "li.location .metadata-text"))
                    else:
                        anchor = _one(card, "h3 a[href]")
                        title = _text(anchor)
                        department = _text(_definition(card, "department"))
                    if not _ROLE.search(title) or (profile == "vienna" and not _VIENNA_ENGLISH.search(title)):
                        continue
                    target = urljoin(url, str(anchor.get("href", "")))
                    identity = _identity(profile, target)
                    if identity is None:
                        raise ValueError("Unexpected official university vacancy URL")
                    deadline = None
                    if profile == "maastricht":
                        deadline = _date(_text(_one(card, "td.colShifttype .jobShifttype")), "%d-%m-%Y")
                    elif profile == "amsterdam":
                        deadline = _time_date(_one(card, ".end-date .date-metadata"), numeric=True)
                    elif profile == "utrecht":
                        deadline = _time_date(_one(_definition(card, "application deadline"), "time"))
                    post = self.make(
                        title=title, url=target, deadline=deadline,
                        deadline_text=f"Application deadline: {deadline.isoformat()}" if deadline else None,
                        # A broad faculty label is metadata, not evidence that
                        # a particular research role is medical or economic.
                        # Populate it for display after the advert is checked.
                        extra={"official_requisition_id": identity, "official_listing_unit": department},
                    )
                    previous = posts.get(identity)
                    if previous and (previous.title != post.title or previous.deadline != post.deadline):
                        conflicts.add(identity)
                        raise ValueError("Conflicting official vacancy cards for one identity")
                    posts.setdefault(identity, post)
                except (ValueError, TypeError) as exc:
                    self.discovery_parse_errors.append(str(exc))
        return [post for identity, post in posts.items() if identity not in conflicts]

    async def fetch_detail(self, post: JobPostSchema) -> str | None:
        profile = self._profile()
        identity = _identity(profile, post.url)
        for key in ("official_detail_verified", "official_subject_text"):
            post.extra.pop(key, None)
        post.extra["official_detail_failure_stage"] = "parse"
        if identity is None or post.extra.get("official_requisition_id") != identity:
            raise ValueError("Unexpected official university advert identity")
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
        if _identity(profile, final) != identity:
            raise ValueError("Official university advert redirected to another vacancy")
        soup = BeautifulSoup(response.text, "lxml")
        canonical = _one(soup, 'link[rel~="canonical"]').get("href")
        if not isinstance(canonical, str) or _identity(profile, canonical) != identity:
            raise ValueError("Official university canonical identity disagrees")
        schema = None
        deadline = post.deadline
        if profile in {"vienna", "maastricht"}:
            root = _one(soup, "span.jobdescription")
            content = html_to_text(str(root))
            if profile == "vienna":
                accepted_titles = {normalize_title(post.title)}
                for stage in ("predoctoral", "postdoctoral"):
                    if normalize_title(post.title) == f"scientific project assistant {stage}":
                        accepted_titles.add(f"{stage} scientific project assistant")
                headings = [n for n in root.select("h2, p:has(> strong)") if normalize_title(_text(n)) in accepted_titles]
                if not headings or normalize_title(str(_one(soup, 'meta[property="og:title"]').get("content", ""))) != normalize_title(post.title):
                    raise ValueError("Official Vienna advert title disagrees")
                ids = re.findall(r"\bJob ID:\s*([1-9]\d{2,6})\b", content)
                if not ids or len(set(ids)) != 1:
                    raise ValueError("Official Vienna requisition identity missing")
                post.extra["official_employer_job_id"] = ids[0]
                subject = _section_text(root, _VIENNA_SECTIONS)
                labels = [n for n in root.select("p") if "Application deadline:" in _text(n)]
                dates = []
                for node in labels:
                    match = re.fullmatch(r"(?:Data protection\s+)?\u200b?Application deadline:\s*(\d{1,2}/\d{1,2}/20\d{2})(?:\s+mm/dd/yy)?", _text(node))
                    if not match:
                        raise ValueError("Official Vienna closing date is qualified")
                    dates.append(_date(match.group(1), "%m/%d/%Y"))
                if not dates or len(set(dates)) != 1:
                    raise ValueError("Official Vienna closing date missing or conflicting")
                deadline = dates[0]
            else:
                if normalize_title(_text(_one(soup, "h1"))) != normalize_title(post.title):
                    raise ValueError("Official Maastricht advert title disagrees")
                subject = _section_text(root, _MAASTRICHT_SECTIONS, bold=True)
                _consistent_detail_cutoffs(root, deadline)
        elif profile == "amsterdam":
            schema = _job_schema(soup)
            titles = [_text(n) for n in soup.select("h1")]
            ids = [_text(n) for n in soup.select(".vacancy-header li.custom-filter04 .metadata-text, .vacancy-sticky li.custom-filter04 .metadata-text")]
            if not titles or any(normalize_title(t) != normalize_title(post.title) for t in titles) or not ids or set(ids) != {identity}:
                raise ValueError("Official Amsterdam advert identity disagrees")
            sections = soup.select(".vacancy-accordion:has(.accordion-title h2)")
            subject_nodes = [n for n in sections if _text(_one(n, ".accordion-title h2")).casefold().rstrip("?:") in _AMSTERDAM_DUTIES | _AMSTERDAM_QUALIFICATIONS]
            section_labels = {_text(_one(n, ".accordion-title h2")).casefold().rstrip("?:") for n in subject_nodes}
            if not section_labels & _AMSTERDAM_DUTIES or not section_labels & _AMSTERDAM_QUALIFICATIONS:
                raise ValueError("Official Amsterdam duties or qualifications missing")
            subject = "\n".join(dict.fromkeys(html_to_text(str(n)) for n in subject_nodes))
            body = schema.get("description")
            if not isinstance(body, str) or len(body) < 100:
                raise ValueError("Official Amsterdam advert body missing")
            content = html_to_text(body)
            dates = [_time_date(n, numeric=True) for n in soup.select(".vacancy-header .end-date .date-metadata, .vacancy-sticky .end-date .date-metadata")]
            if not dates or set(dates) != {deadline}:
                raise ValueError("Official Amsterdam closing dates disagree")
        else:
            schema = _job_schema(soup)
            root = _one(soup, "main #block-primary-content")
            if normalize_title(_text(_one(root, "h1"))) != normalize_title(post.title):
                raise ValueError("Official Utrecht advert title disagrees")
            identifiers = {str(n.get("data-web_page_id")) for n in root.select('script[type="HIRESERVE/Apply"]')}
            value = schema.get("identifier", {}).get("value", "")
            if not re.fullmatch(r"[1-9]\d+-EN-\d+", value) or identifiers != {value.split("-", 1)[0]}:
                raise ValueError("Official Utrecht requisition identity disagrees")
            post.extra["official_employer_job_id"] = value
            blocks = root.select(".content-block-vacancy .content-block__inner")
            if not blocks:
                raise ValueError("Official Utrecht advert body missing")
            content = "\n".join(html_to_text(str(n)) for n in blocks)
            subject = _section_text(root, {"your job", "your qualities"})
            if _time_date(_one(_definition(root, "application deadline"), "time")) != deadline:
                raise ValueError("Official Utrecht closing dates disagree")
        if schema is not None:
            if normalize_title(str(schema.get("title", ""))) != normalize_title(post.title):
                raise ValueError("Official structured advert title disagrees")
            valid = schema.get("validThrough")
            if not isinstance(valid, str) or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}(?:T[0-9:]+Z)?", valid) or datetime.fromisoformat(valid.replace("Z", "+00:00")).date() != deadline:
                raise ValueError("Official structured closing date disagrees")
            posted = schema.get("datePosted")
            if isinstance(posted, str):
                post.date_posted = datetime.fromisoformat(posted.replace("Z", "+00:00")).date()
        if len(subject) < 80 or len(content) < 150:
            raise ValueError("Official university advert evidence incomplete")
        post.deadline = deadline
        post.deadline_text = f"Application deadline: {deadline.isoformat()}" if deadline else None
        # These reviewed employers' country defaults are explicit provenance,
        # not a claim that a city/location label was found in every advert.
        post.country, post.region = detect_location(self.cfg.country or "")
        post.extra.pop("source_country_default", None)
        post.extra["official_country_basis"] = "reviewed_source_profile"
        post.department = post.extra.get("official_listing_unit")
        post.extra["official_subject_text"] = post.title + "\n" + subject
        post.extra["official_detail_verified"] = True
        post.extra["final_url"] = final
        return content
