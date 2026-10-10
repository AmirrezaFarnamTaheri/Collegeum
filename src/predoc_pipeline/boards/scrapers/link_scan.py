"""Generic HTML job-board scraper.

Most university boards (Varbi, KU, Cambridge, U of T, jobs.ac.uk search, EURAXESS, EJM...) render
listings as plain links whose anchor text is the job title. Instead of brittle per-site selectors,
this scraper keeps every <a> whose absolute URL matches `link_pattern`, and reads institution,
location and dates from the surrounding "card" (table row / list item / article / div.card).

Options:
  url / urls              listing page(s)
  link_pattern            regex matched against the absolute link URL (required unless `selectors`)
  selectors               optional structured mode: {item, title, link, institution, location, deadline, posted}
  institution_from_context  guess employer from the card text (for multi-employer aggregators)
  bare_date_is_deadline   treat an unlabeled date in the card as the deadline (e.g. KU table)
  render                  render with Playwright first (JS-only boards); requires `playwright install chromium`
  wait_for                CSS selector to wait for when rendering
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from ..models import JobPostSchema
from ..utils.dates import extract_deadline, find_dates, parse_posted
from ..utils.geo import detect_location
from ..utils.text import absolutize, clean_ws, truncate
from .base import BaseScraper, register

log = logging.getLogger(__name__)

GENERIC_ANCHORS = {
    "read more", "more", "apply", "apply now", "details", "view", "view job", "view details",
    "more info", "more information", "learn more", "here", "click here", "link", "see more",
    "job details", "show more", "next", "previous", "login", "sign in", "share",
    "link for job posting", "link to job posting", "link for job", "link to job",
    "apply here", "apply online", "view posting", "job posting", "full posting",
}
_CARD_CLASS = re.compile(r"card|job|result|vacanc|listing|item|teaser|views-row|posting|position|opening",
                         re.IGNORECASE)
_INSTITUTION_RX = re.compile(
    r"universit|college|school|institut|centre|center|\bbank\b|academy|foundation|council|hochschule|"
    r"[ée]cole|politecnico|fundaci|agency|ministry|laborator|observatory|\btrust\b|OECD|\bIMF\b|CEPR|"
    r"\bEUI\b|\bLSE\b|\bUCL\b|\bETH\b|\bgmbh\b|\bltd\b|\binc\b",
    re.IGNORECASE,
)
# Nav links to people/alumni pages, not job ads ("Research Assistants", "Our predocs", "Pre-docs").
_PEOPLE_NAV = re.compile(r"^(?:our\s+|current\s+|former\s+|meet\s+(?:our|the)\s+)?(?:pre-?docs?|pre-?doctoral\s+"
                         r"(?:fellows|researchers|students|program(?:me)?)|research\s+(?:assistants|associates|fellows)|"
                         r"people|team|staff|alumni|faculty|placements?)$", re.IGNORECASE)

_EXCLUDED_URL_RX = re.compile(
    r"/people/(?:faculty/|staff/|index|$|\?)|"
    r"/faculty/(?:index|pages/profile|personal|$|\?)|"
    r"/staff/(?:index|directory|$|\?)|"
    r"/alumni/|/experts?/|"
    r"/news/stories/|"
    r"/was-wir-bieten|/diversitaet|/studierende|/stellenangebote|"
    r"/ra-matching|/learn-more|/before-applying|/courses|/private-firms|/pre-workshop|"
    r"facid=|facId=",
    re.IGNORECASE,
)

_EXCLUDED_TITLE_RX = re.compile(
    r"^(?:(?:our\s+|current\s+|former\s+|meet\s+(?:our|the)\s+|external\s+|academic\s+)?"
    r"(?:faculty|staff|people|team|alumni|directors|board|students|studierende)|"
    r"was\s+wir\s+bieten|studierende|diversit[äa]t|stellenangebote|karriere|"
    r"why\s+do\s+a\s+pre-?doc\??|ra\s+award\s+program|before\s+applying|"
    r"benefits|our\s+culture|work\s+with\s+us|join\s+us|contact\s+us|"
    r"postdocs?|faq|privacy\s+policy|asynchronous\s+courses|pre-?docs?\s+in\s+industry|"
    r".*pre-?doctoral\s+research\s+in\s+economics\s+\(pre\)\s+workshop.*|"
    r".*students\s+achieve\s+outstanding\s+placements.*)$",
    re.IGNORECASE,
)
_POSTED_LABEL = re.compile(r"(date\s+placed|posted(?:\s+on)?|published(?:\s+on)?|date\s+posted|"
                           r"publication\s+date|placed\s+on)\s*[:\-]?\s*", re.IGNORECASE)
_SPONSORING_INST_RX = re.compile(r"^(?:sponsoring\s+)?institution\s*:\s*(.*)$", re.IGNORECASE)
_NON_INST_PREFIX_RX = re.compile(r"^(closes?|deadline|salary|location)")
_DEPT_RX = re.compile(r"department|faculty|institute|school of|centre|center", re.IGNORECASE)


def find_card(a: Tag, max_chars: int = 1800) -> Tag:
    """Closest ancestor that looks like a listing card; falls back to the parent."""
    node: Tag | None = a
    for _ in range(7):
        node = node.parent if node is not None else None
        if node is None or node.name in ("body", "html", "[document]"):
            break
        text_len = len(node.get_text(" ", strip=True))
        if text_len > max_chars:
            break
        classes: str | list[str] = node.get("class") or []
        class_text = classes if isinstance(classes, str) else " ".join(classes)
        if node.name in ("tr", "li", "article") or _CARD_CLASS.search(class_text):
            return node
    return a.parent if isinstance(a.parent, Tag) else a


def card_lines(card: Tag) -> list[str]:
    raw = card.get_text("\n", strip=True).split("\n")
    return [clean_ws(x) for x in raw if clean_ws(x)]


def guess_institution(lines: list[str], title: str) -> str | None:
    tnorm = title.lower()
    for ln in lines:
        low = ln.lower()
        if low == tnorm or len(ln) > 140 or len(ln) < 3:
            continue
        m_inst = _SPONSORING_INST_RX.match(ln)
        if m_inst:
            return m_inst.group(1).strip(" -|•·")
        if _INSTITUTION_RX.search(ln) and not _NON_INST_PREFIX_RX.match(low):
            return ln.strip(" -|•·")
    return None


def previous_heading(a: Tag) -> str:
    """Nearest heading above a link; bold text only if it isn't a label like 'Details:'."""
    for tags in (["h2", "h3", "h4", "h5"], ["strong", "b"]):
        h = a.find_previous(tags)
        text = clean_ws(h.get_text(" ")).rstrip(":") if h else ""
        if text and text.lower() not in GENERIC_ANCHORS and len(text) > 8:
            return text
    return ""


def posted_from_text(text: str) -> Any:
    m = _POSTED_LABEL.search(text)
    return parse_posted(text[m.end(): m.end() + 40]) if m else None


@register
class LinkScanScraper(BaseScraper):
    type_name = "link_scan"

    async def fetch_raw_postings(self) -> list[Any]:
        param = self.opt("pagination_param")
        max_pages = int(self.opt("max_pages", 1))

        if not param and max_pages <= 1:
            async def get(u: str) -> tuple[str, str]:
                return u, (await self._render(u) if self.opt("render") else await self.http.get_text(u))
            return await self.fetch_each(get)

        out: list[tuple[str, str]] = []
        errors: list[str] = []
        pattern = re.compile(self.opt("link_pattern", r".+"), re.IGNORECASE)
        for base_url in self.urls():
            for page in range(1, max_pages + 1):
                page_url = self._format_page_url(base_url, param, page)
                try:
                    html = (
                        await self._render(page_url)
                        if self.opt("render")
                        else await self.http.get_text(page_url)
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{page_url}: {exc}")
                    log.warning("%s: page %d (%s) failed: %s", self.name, page, page_url, exc)
                    break
                out.append((page_url, html))
                soup = BeautifulSoup(html, "lxml")
                matching = [
                    a["href"]
                    for a in soup.find_all("a", href=True)
                    if pattern.search(absolutize(page_url, str(a["href"])))
                ]
                if not matching:
                    break
        if errors and not out:
            raise RuntimeError("; ".join(errors)[:500])
        return out

    def _format_page_url(self, base_url: str, param: str | None, page: int) -> str:
        if "{page}" in base_url:
            return base_url.format(page=page)
        if not param or page == 1:
            return base_url
        parts = urlsplit(base_url)
        qs = parse_qs(parts.query, keep_blank_values=True)
        qs[param] = [str(page)]
        new_query = urlencode(qs, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))

    async def _render(self, url: str) -> str:
        from .university_ats import render_page  # lazy: playwright is optional
        return await render_page(url, wait_for=self.opt("wait_for"))

    # ---------------------------------------------------------------------------------
    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        posts: list[JobPostSchema] = []
        for base, html in raw_data:
            soup = BeautifulSoup(html, "lxml")
            if self.opt("selectors"):
                posts.extend(self._parse_selectors(base, soup))
            else:
                posts.extend(self._parse_links(base, soup))
        return posts

    def _parse_links(self, base: str, soup: BeautifulSoup) -> list[JobPostSchema]:
        pattern = re.compile(self.opt("link_pattern", r".+"), re.IGNORECASE)
        min_len = int(self.opt("title_min_len", 6))
        posts, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = absolutize(base, str(a["href"]))
            if not pattern.search(href) or href in seen or _EXCLUDED_URL_RX.search(href):
                continue
            title = clean_ws(a.get_text(" "))
            if title.lower() in GENERIC_ANCHORS or len(title) < min_len:
                title = clean_ws(str(a.get("title") or a.get("aria-label") or ""))
            if (title.lower() in GENERIC_ANCHORS or len(title) < min_len) and self.opt("heading_titles"):
                title = previous_heading(a)  # "Details" link under an <h3>Job title</h3>
            if (title.lower() in GENERIC_ANCHORS or len(title) < min_len) and self.opt("card_title"):
                card = find_card(a)
                c_lines = card_lines(card)
                for ln in c_lines:
                    if (
                        len(ln) >= min_len
                        and ln.lower() not in GENERIC_ANCHORS
                        and not _PEOPLE_NAV.match(ln)
                        and not _EXCLUDED_TITLE_RX.match(ln)
                    ):
                        title = ln
                        break
            if (
                not title
                or title.lower() in GENERIC_ANCHORS
                or len(title) < min_len
                or _PEOPLE_NAV.match(title)
                or _EXCLUDED_TITLE_RX.match(title)
            ):
                continue
            seen.add(href)
            posts.append(self._post_from_card(href, title, find_card(a)))
        return posts

    def _post_from_card(self, href: str, title: str, card: Tag) -> JobPostSchema:
        lines = card_lines(card)
        text = " \n ".join(lines)
        rest = " \n ".join(ln for ln in lines if ln != title)
        deadline, deadline_text = extract_deadline(rest)
        if not deadline and self.opt("bare_date_is_deadline"):
            dates = find_dates(rest)
            if dates:
                deadline, deadline_text = dates[-1][1], None
        institution = self.cfg.institution
        if self.opt("institution_from_context") or not institution:
            institution = guess_institution(lines, title) or institution
        # Single-institution boards already know their country; only aggregators read it from the card.
        country = None if self.cfg.country else detect_location(rest)[0]
        return self.make(
            title=title, url=href, institution=institution or "",
            location=country, department=self._department(lines, title),
            date_posted=posted_from_text(text), deadline=deadline, deadline_text=deadline_text,
            description_snippet=truncate(rest, 500),
        )

    def _department(self, lines: list[str], title: str) -> str | None:
        for ln in lines:
            if ln != title and _DEPT_RX.search(ln) and len(ln) < 160:
                return ln
        return None

    def _parse_selectors(self, base: str, soup: BeautifulSoup) -> list[JobPostSchema]:
        sel: dict[str, str] = self.opt("selectors")
        posts = []

        def pick(node: Tag, key: str) -> str | None:
            if not sel.get(key):
                return None
            el = node.select_one(sel[key])
            return clean_ws(el.get_text(" ")) if el else None

        for item in soup.select(sel["item"]):
            link_el = item.select_one(sel.get("link", "a[href]"))
            if not link_el or not link_el.get("href"):
                continue
            title = pick(item, "title") or clean_ws(link_el.get_text(" "))
            if not title:
                continue
            deadline_raw = pick(item, "deadline")
            deadline, deadline_text = extract_deadline(f"deadline: {deadline_raw}") if deadline_raw else (None, None)
            posts.append(self.make(
                title=title, url=absolutize(base, str(link_el["href"])),
                institution=pick(item, "institution") or self.cfg.institution or "",
                location=pick(item, "location"), deadline=deadline, deadline_text=deadline_text or deadline_raw,
                date_posted=parse_posted(pick(item, "posted")),
                description_snippet=truncate(item.get_text(" ", strip=True), 500),
            ))
        return posts
