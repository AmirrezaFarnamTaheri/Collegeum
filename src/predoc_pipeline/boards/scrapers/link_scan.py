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
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from ...core.output_quality import application_url_issue
from ..models import JobPostSchema
from ..utils.dates import extract_deadline, find_dates, parse_posted, today
from ..utils.geo import detect_location
from ..utils.text import absolutize, clean_ws, truncate
from .base import BaseScraper, SourceSkipped, register

log = logging.getLogger(__name__)

GENERIC_ANCHORS = {
    "read more", "more", "apply", "apply now", "details", "view", "view job", "view details",
    "more info", "more information", "learn more", "here", "click here", "link", "see more",
    "job details", "show more", "next", "previous", "login", "sign in", "share",
    "mehr erfahren", "stellenangebot", "zum stellenangebot", "weiterlesen", "jobangebot",
    "link for job posting", "link to job posting", "link for job", "link to job",
    "apply here", "apply online", "view posting", "job posting", "full posting",
    "vacancy notice", "further particulars",
}
_CARD_CLASS = re.compile(r"card|job|result|vacanc|listing|item|teaser|views-row|posting|position|opening|stellenangebot",
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


# A role mention inside a news article is not a vacancy. Only treat role
# titles at the start of a link label as job candidates. An explicit
# application call to action or a recruiting announcement naming a role
# also counts. URL paths identifying postings are checked separately.
_VACANCY_LINK_LABEL = re.compile(
    r"^\s*(?:(?:pre[-\s]?doc(?:toral)?|post[-\s]?doc(?:toral)?)\s+"
    r"(?:research\s+)?(?:assistant|associate|analyst|fellow(?:ship)?|"
    r"researcher|position|opportunity|vacancy|job|scholar|in\b|at\b)"
    r"|(?:pre[-\s]?doc(?:toral)?|post[-\s]?doc(?:toral)?)\s*$"
    r"|research\s+(?:assistant|associate|analyst|fellow|scientist)\b"
    r"|data\s+scientist\b)"
    r"|\b(?:job|position|vacancy)\s+(?:opening|posting|application)\b"
    r"|\bapply\s+(?:now|online|for\s+(?:the|this|a))\b"
    r"|\b(?:hiring|recruiting|openings?|vacanc(?:y|ies)|"
    r"jobs?|positions?|roles?|opportunit(?:y|ies))\b.{0,90}?"
    r"\b(?:pre[-\s]?doc(?:toral)?|post[-\s]?doc(?:toral)?|"
    r"research\s+(?:assistant|associate|analyst|fellow|scientist)|"
    r"data\s+scientist)\b",
    re.IGNORECASE,
)
_VACANCY_LINK_PATH = re.compile(
    r"/(?:jobs?|jobpostings?|positions?|postings?|apply)/[^/?#]{3,}",
    re.IGNORECASE,
)


def _verified_empty_cohort_rows(
    raw_data: list[Any], required_cells: object,
) -> bool:
    """Match the *same* employer cohort row; reject changed or extra cohorts."""
    if (
        not isinstance(required_cells, list)
        or len(required_cells) < 3
        or not all(isinstance(x, str) and x.strip() for x in required_cells)
    ):
        return False

    def norm(text: str) -> str:
        return clean_ws(text).casefold().replace("–", "-").replace("—", "-")

    required = [norm(x) for x in required_cells]
    role, rows = required[0], []
    for _, html in raw_data:
        for tr in BeautifulSoup(html, "lxml").select("tr"):
            cells = [norm(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
            if role in cells:
                rows.append(cells)
    return bool(rows) and all(all(term in cells for term in required) for cells in rows)


def _verified_empty_has_job_links(raw_data: list[Any]) -> bool:
    """A careers-page footer cannot prove emptiness if a job-like link appears."""
    for base, html in raw_data:
        for anchor in BeautifulSoup(html, "lxml").select("a[href]"):
            label = clean_ws(anchor.get_text(" ", strip=True))
            href = absolutize(base, str(anchor["href"]))
            if _VACANCY_LINK_LABEL.search(label) or _VACANCY_LINK_PATH.search(href):
                return True
    return False


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
        skip_templates = bool(self.opt("skip_unresolved_link_templates", False))
        # Advert links found so far that carry a real, unique identity. Only
        # when nothing usable has been found at all may the source be
        # declared an unresolved-template state.
        usable_links = 0
        template_page_seen = False
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
                    self.discovery_fetch_errors.append(f"{type(exc).__name__} at page {page}")
                    log.warning("%s: page %d (%s) failed: %s", self.name, page, page_url, exc)
                    break
                out.append((page_url, html))
                if skip_templates:
                    matched, usable = self._link_template_state(page_url, html, pattern)
                    if matched and not usable and not usable_links:
                        # Stop this endpoint's template-only pagination, but
                        # still inspect other configured URLs. A later URL may
                        # have real vacancies or expose a fetch failure.
                        template_page_seen = True
                        break
                    usable_links += usable
                soup = BeautifulSoup(html, "lxml")
                matching = [
                    a["href"]
                    for a in soup.find_all("a", href=True)
                    if pattern.search(absolutize(page_url, str(a["href"])))
                ]
                if not matching:
                    break
                if page == max_pages and max_pages > 1:
                    # A populated terminal page is not proof that all later
                    # pages are empty. Surface the bounded scan as partial.
                    self.discovery_limits.append(
                        f"pagination page cap {max_pages} reached for {base_url}"
                    )
        if errors and not out:
            raise RuntimeError("; ".join(errors)[:500])
        if template_page_seen and not usable_links and not self.discovery_fetch_errors:
            raise SourceSkipped("upstream advert links have unresolved IDs")
        return out

    def _link_template_state(
        self, page_url: str, html: str, pattern: re.Pattern[str]
    ) -> tuple[int, int]:
        """(matching links, matching links that are not unresolved templates).

        A page with no matching link at all is not a template page: an empty
        page is simply empty, and it must not be reported as the known
        upstream template state.
        """
        soup = BeautifulSoup(html, "lxml")
        matched = [
            absolutize(page_url, str(a["href"]))
            for a in soup.find_all("a", href=True)
            if pattern.search(absolutize(page_url, str(a["href"])))
        ]
        if not matched:
            return 0, 0
        usable = sum(
            1 for href in matched
            if application_url_issue(href) != "unresolved-url-template"
        )
        return len(matched), usable

    def _format_page_url(self, base_url: str, param: str | None, page: int) -> str:
        if "{page}" in base_url:
            return base_url.format(page=page)
        if not param or page == 1:
            return base_url
        parts = urlsplit(base_url)
        qs = parse_qs(parts.query, keep_blank_values=True)
        qs[param] = [str(page - 1 if self.opt("pagination_zero_based") else page)]
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
        # Opt-in for small providers that explicitly say when there are no
        # current vacancies. A redirected article or layout regression must
        # not silently masquerade as a healthy empty listing page.
        marker = self.opt("verified_empty_marker")
        if marker and not posts:
            expected = clean_ws(str(marker)).casefold()
            found = any(
                expected in clean_ws(BeautifulSoup(html, "lxml").get_text(" ", strip=True)).casefold()
                for _, html in raw_data
            )
            if not found:
                self.discovery_parse_errors.append("Verified no-vacancies notice missing")
            else:
                required_cells = self.opt("verified_empty_row_cells")
                if required_cells is not None and not _verified_empty_cohort_rows(
                    raw_data, required_cells
                ):
                    self.discovery_parse_errors.append(
                        "Verified no-vacancies cohort row changed or missing"
                    )
                if self.opt("verified_empty_reject_job_links") and _verified_empty_has_job_links(
                    raw_data
                ):
                    self.discovery_parse_errors.append(
                        "Job-like application link present on purported empty careers page"
                    )
                # Annual hiring cycles must not remain permanently 'healthy
                # empty' because last year's page still contains a closed
                # cohort. Bounds are optional for other seasonal sources.
                after = self.opt("verified_empty_after")
                before = self.opt("verified_empty_before")
                if after or before:
                    try:
                        current = today()
                        if (after and current <= date.fromisoformat(after)) or (
                            before and current >= date.fromisoformat(before)
                        ):
                            self.discovery_parse_errors.append(
                                "Verified no-vacancies notice outside its hiring cycle"
                            )
                    except (ValueError, TypeError):
                        self.discovery_parse_errors.append(
                            "Invalid verified no-vacancies hiring cycle dates"
                        )
        if (
            not posts
            and self.opt("skip_unresolved_link_templates", False)
            and not self.discovery_fetch_errors
            and self.discovery_parse_errors
            and all("Unresolved application URL" in reason
                    for reason in self.discovery_parse_errors)
        ):
            # EJME's live Drupal template can emit links ending in [nid].
            # No unique application identity exists. Do not invent a URL,
            # publish garbage, or classify this known upstream state as a
            # successful empty scrape. It will retry automatically next run.
            self.discovery_parse_errors.clear()
            self.discovery_limits.clear()
            raise SourceSkipped("upstream advert links have unresolved IDs")
        return posts

    def _parse_links(self, base: str, soup: BeautifulSoup) -> list[JobPostSchema]:
        pattern = re.compile(self.opt("link_pattern", r".+"), re.IGNORECASE)
        min_len = int(self.opt("title_min_len", 6))
        posts, seen = [], set()
        anchors: list[Tag] = list(soup.find_all("a", href=True))
        if self.opt("open_section_only", False):
            # Some careers pages list archived postings under CURRENTLY CLOSED.
            # Require both markers: a changed layout is not proof of emptiness.
            open_mark = soup.find(string=lambda x: bool(x) and x.strip().upper() == "CURRENTLY OPEN")
            closed_mark = soup.find(
                string=lambda x: bool(x) and x.strip().upper() == "CURRENTLY CLOSED"
            )
            if open_mark is None or closed_mark is None:
                self.discovery_parse_errors.append("Missing open/closed vacancy boundaries")
                return []
            allowed: set[int] = set()
            found_end = False
            for node in open_mark.next_elements:
                if node is closed_mark:
                    found_end = True
                    break
                if isinstance(node, Tag) and node.name == "a" and node.get("href"):
                    allowed.add(id(node))
            if not found_end:
                self.discovery_parse_errors.append("Closed vacancy boundary not reachable")
                return []
            anchors = [a for a in anchors if id(a) in allowed]
        for a in anchors:
            href = absolutize(base, str(a["href"]))
            if not pattern.search(href) or href in seen or _EXCLUDED_URL_RX.search(href):
                continue
            if not self._valid_application_url(href):
                continue
            title = clean_ws(a.get_text(" "))
            if self.opt("prefer_card_heading"):
                # Some research institutes label the clickable link with an
                # internal vacancy code while the actual position title is
                # the nearby H2/H3. Only use a heading within the same card
                # to avoid borrowing the preceding vacancy's title.
                card = find_card(a)
                heading = card.select_one("h2, h3, h4, h5, h6")
                if heading is not None:
                    heading_text = clean_ws(heading.get_text(" "))
                    if min_len <= len(heading_text) <= 300:
                        title = heading_text
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

    def _valid_application_url(self, href: str) -> bool:
        issue = application_url_issue(href)
        if issue is None:
            return True
        # Only an unresolved template qualifies for the known upstream skip.
        # Keep other failure categories without retaining untrusted URLs.
        reason = (
            "Unresolved application URL in listing" if issue == "unresolved-url-template"
            else f"Invalid application URL in listing: {issue}"
        )
        if reason not in self.discovery_parse_errors:
            self.discovery_parse_errors.append(reason)
        return False

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
            href = absolutize(base, str(link_el["href"]))
            pattern = self.opt("link_pattern")
            if pattern and not re.search(pattern, href, re.IGNORECASE):
                continue
            if not self._valid_application_url(href):
                continue
            title = pick(item, "title") or clean_ws(link_el.get_text(" "))
            if not title:
                continue
            deadline_raw = pick(item, "deadline")
            deadline, deadline_text = extract_deadline(f"deadline: {deadline_raw}") if deadline_raw else (None, None)
            posts.append(self.make(
                title=title, url=href,
                institution=pick(item, "institution") or self.cfg.institution or "",
                location=pick(item, "location"), deadline=deadline, deadline_text=deadline_text or deadline_raw,
                date_posted=parse_posted(pick(item, "posted")),
                description_snippet=truncate(item.get_text(" ", strip=True), 500),
            ))
        return posts
