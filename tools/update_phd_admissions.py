"""Rotate official Economics PhD admissions checks without reusing third-party dates.

Only programme URLs are adopted as discovery leads from the MIT-licensed source.
A date is surfaced only when the university's own page explicitly contains a
current-year/future-year date with local Economics PhD + deadline context.

This standalone monitor never imports the vacancies pipeline, touches journals,
publishes to Telegram, or uses LLM guesses. A failed/blocked check fails closed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

# CLI scripts also run with "python -S tools/script.py": keep that mode safe.
if __package__:
    from .official_html_validation import official_html_response_problem
    from .official_robots import parse_official_robots
else:
    from official_html_validation import official_html_response_problem
    from official_robots import parse_official_robots

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "config/phd_admissions_seeds.json"
PUBLIC = ROOT / "docs/data/phd_admissions.json"
USER_AGENT = "CollegeumAdmissionsMonitor/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
CHECK_INTERVAL = timedelta(days=11)
# Bump only when official HTML interpretation changes. Readable negatives
# checked with an older revision receive one safe early recheck.
EXTRACTOR_REVISION = "2026-11-23-admissions-v4"
EXPIRY = timedelta(days=14)
MAX_HTML_BYTES = 1024 * 1024
MAX_ROBOTS_BYTES = 256 * 1024
DATE_PATTERN = re.compile(
    r"\b(?P<iso>20\d{2}-\d{2}-\d{2})\b|"
    r"\b(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s*,?\s*(?P<year>20\d{2})\b|"
    r"\b(?P<month2>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(?P<day2>\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(?P<year2>20\d{2})\b|"
    r"(?<!\d)(?P<n1>\d{1,2})[./](?P<n2>\d{1,2})[./](?P<ny>20\d{2})\b",
    re.I,
)
PROGRAMME = re.compile(
    r"(?:economics?\s+(?:mres\s*/\s*)?(?:ph\.?d\.?|doctor(?:al|ate))|"
    r"(?:ph\.?d\.?|doctor(?:al|ate))\s+(?:in\s+)?economics?|"
    r"(?:ph\.?d\.?|doctoral)\s+programmes?\s+in\s+[^.?!\n]{0,80}?\beconomics?|"
    r"doctor(?:al|ate)\s+program(?:me)?\s+in\s+economics?|"
    r"doctor(?:al|ate)\s+program(?:me)?\s+\([^)]{0,80}\beconomics?\b[^)]*\)|"
    r"department\s+of\s+economics\b[^.?!]{0,150}\b"
    r"(?:ph\.?d\.?|doctoral)\s+program(?:me)?)", 
    re.I,
)
DEADLINE = re.compile(
    r"(?:application(?:s)?\s+)?deadlines?|"
    r"applications?\s+(?:close|due|must\s+be\s+submitted)|"
    r"apply\s+by|"
    r"submission\s+deadline|"
    r"closes?\s+on|closing\s+date|no\s+later\s+than|through\b", 
    re.I,
)
# Explicitly exclude ancillary document, exam, funding and decision deadlines.
# Their dates can sit immediately beside the programme application deadline.
ANCILLARY = re.compile(
    r"\b(?:document|supporting|transcript|reference|recommendation|"
    r"language|test|gmat|gre|scholarship|appeal|decision|interview|"
    r"mentoring|mentorship|mba|undergraduate|workshop|orientation)\b",
    re.I,
)

STATUSES = {
    "unverified", "verified", "no_explicit_deadline", "ambiguous_deadline",
    "robots_disallowed", "robots_unavailable", "fetch_failed",
    "unsafe_redirect", "insecure_source", "stale",
}


class PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self.ignored = 0
        self.headings: list[str] = []
        self._heading_parts: list[str] = []
        self._in_h1 = False
        self.links: list[tuple[str, str]] = []
        self._anchor_href: str | None = None
        self._anchor_parts: list[str] = []
        self.blocks: list[str] = []
        self.tagged_blocks: list[tuple[str, str]] = []
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] | None = None
        self._row_cells: list[str] | None = None
        self.address_blocks: list[str] = []
        self._block_tag: str | None = None
        self._block_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._current_table = []
        if tag == "tr":
            self._row_cells = []
        if tag == "h1":
            self._in_h1 = True
            self._heading_parts = []
        if (
            tag in {"h1", "h2", "h3", "h4", "p", "li", "dt", "dd", "th", "td", "address"}
            and self._block_tag is None
        ):
            self._block_tag = tag
            self._block_parts = []
        if tag == "a" and not self.ignored:
            self._anchor_href = dict(attrs).get("href")
            self._anchor_parts = []
        if tag in {"script", "style", "svg", "noscript", "template"}:
            self.ignored += 1
        elif tag in {"p", "div", "h1", "h2", "h3", "li", "tr", "br"}:
            self.chunks.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1":
            heading = " ".join(" ".join(self._heading_parts).split())
            if heading:
                self.headings.append(heading)
            self._in_h1 = False
        if tag == "a":
            label = " ".join(" ".join(self._anchor_parts).split())
            if self._anchor_href and label:
                self.links.append((self._anchor_href, label))
            self._anchor_href = None
            self._anchor_parts = []
        if tag == self._block_tag:
            block = " ".join(" ".join(self._block_parts).split())
            if block:
                self.blocks.append(block)
                self.tagged_blocks.append((tag, block))
                if tag in {"td", "th"} and self._row_cells is not None:
                    self._row_cells.append(block)
                if tag == "address":
                    self.address_blocks.append(block)
            self._block_tag = None
            self._block_parts = []
        if tag == "tr":
            if self._row_cells and self._current_table is not None:
                self._current_table.append(self._row_cells)
            self._row_cells = None
        if tag == "table":
            if self._current_table:
                self.tables.append(self._current_table)
            self._current_table = None
        if tag in {"script", "style", "svg", "noscript", "template"}:
            self.ignored = max(0, self.ignored - 1)
        elif tag in {"p", "div", "h1", "h2", "h3", "li", "tr"}:
            self.chunks.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.chunks.append(data)
            if self._in_h1:
                self._heading_parts.append(data)
            if self._anchor_href is not None:
                self._anchor_parts.append(data)
            if self._block_tag is not None:
                self._block_parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self.chunks).split())


def _parse_date(match: re.Match[str]) -> date | None:
    try:
        if match.group("iso"):
            return date.fromisoformat(match.group("iso"))
        if match.group("ny"):
            first, second, year = (
                int(match.group("n1")), int(match.group("n2")),
                int(match.group("ny")),
            )
            # A country-agnostic parser must not guess whether 03/04
            # means March 4 or April 3. Only unambiguous dates qualify.
            if first <= 12 and second <= 12:
                return None
            if second <= 12:
                return date(year, second, first)
            if first <= 12:
                return date(year, first, second)
            return None
        day = int(match.group("day") or match.group("day2"))
        month_name = (match.group("month") or match.group("month2")).lower()[:3]
        months = (
            "jan", "feb", "mar", "apr", "may", "jun",
            "jul", "aug", "sep", "oct", "nov", "dec",
        )
        month = months.index(month_name) + 1
        return date(int(match.group("year") or match.group("year2")), month, day)
    except (ValueError, TypeError):
        return None


def _structured_deadline_candidates(
    parser: PageText, *, now: datetime, programme_page: bool,
) -> list[tuple[str, str]]:
    """Corroborate dates and their explicit roles in the same table column or list group.

    A date preceding its label is not a normal adjacent text deadline. Never
    match an unrelated programme, neighboring date column or next date group.
    """
    candidates: list[tuple[str, str]] = []
    if programme_page:
        for rows in parser.tables:
            for date_row, label_row in zip(rows, rows[1:], strict=False):
                if len(date_row) < 2 or len(date_row) != len(label_row):
                    continue
                for cell, label in zip(date_row, label_row, strict=True):
                    if (
                        re.search(
                            r"\b(?:application deadline|deadline for submission of "
                            r"(?:your |the )?application)\b", label, re.I,
                        ) is None
                        or ANCILLARY.search(label)
                    ):
                        continue
                    dates = [
                        (day, match.group())
                        for match in DATE_PATTERN.finditer(cell)
                        if (day := _parse_date(match)) is not None
                        and now.date() <= day <= date(now.year + 2, 12, 31)
                    ]
                    if len({day for day, _ in dates}) != 1:
                        continue
                    day, printed = dates[0]
                    # The original date and its role occur in the same
                    # official table column, not necessarily adjacent in HTML.
                    excerpt = f"{label.rstrip('.:')} (table): {printed}"
                    candidates.append((day.isoformat(), excerpt[:180]))
    if (
        any(re.search(r"\b(?:ph\.?d\.?|doctoral)\b", h, re.I)
            for h in parser.headings)
        or re.search(
            r"\b(?:ph\.?d\.?|doctoral)\b", parser.text()[:4000], re.I,
        )
    ):
        blocks = parser.tagged_blocks
        for index, (tag, heading) in enumerate(blocks):
            if tag not in {"h2", "h3"}:
                continue
            dates = [
                (day, match.group())
                for match in DATE_PATTERN.finditer(heading)
                if (day := _parse_date(match)) is not None
                and now.date() <= day <= date(now.year + 2, 12, 31)
            ]
            if len({day for day, _ in dates}) != 1:
                continue
            group: list[tuple[str, str]] = []
            for later_tag, later_block in blocks[index + 1:index + 35]:
                if later_tag in {"h1", "h2", "h3"}:
                    break
                group.append((later_tag, later_block))
            if not (
                any(re.search(r"\bapplication deadline for\b", b, re.I)
                    for _, b in group)
                and any(
                    tag == "li" and re.fullmatch(r"Economics(?:\s+PhD)?", b, re.I)
                    for tag, b in group
                )
            ):
                continue
            day, printed = dates[0]
            # Label, subject and date are explicitly in the same
            # institutional list group.
            candidates.append((
                day.isoformat(), f"Application deadline for Economics (list): {printed}",
            ))
    return candidates


def collect_official_deadline(
    html: str, *, now: datetime, source_url: str | None = None,
) -> tuple[str, str | None, str | None]:
    """Extract only an explicit, unambiguous date near PhD economics context.

    No inference from month/day without a year, academic intake, an expired date,
    another subject, or an admissions aggregator is allowed.
    """
    parser = PageText()
    parser.feed(html[:MAX_HTML_BYTES])
    text = parser.text()[:MAX_HTML_BYTES]
    # A specific programme H1 makes its admission schedule authoritative.
    programme_page = any(PROGRAMME.search(heading) for heading in parser.headings)
    if not programme_page:
        # An official graduate division programme page may use the H1
        # "Economics" with the doctoral degree and exclusive PhD admission
        # stated in separate sections before its dated application cutoff.
        # Both the exact subject and the doctoral-only qualifier are required.
        programme_page = bool(
            any(re.fullmatch(r"\s*Economics\s*", heading, re.I)
                for heading in parser.headings)
            and re.search(r"\bGraduate Program\s*:\s*Economics\b", text[:12000], re.I)
            and re.search(
                r"\bDoctor of Philosophy\s*\(\s*Ph\.?D\.?\s*\)",
                text[:12000], re.I,
            )
            and re.search(
                r"\bAdmits only Ph\.?D\.? applicants\b", text[:12000], re.I,
            )
            and re.search(r"\bDeadlines to apply\b", text[:12000], re.I)
        )
    if not programme_page:
        # Primary university graduate directories sometimes render a concise
        # per-programme card: H1 "Economics", followed by "Degrees Offered:
        # Doctor of Philosophy (PhD)" and a dated "Application Deadline".
        # Requiring the exact doctoral degree entry prevents a Master's card
        # or a general programme list from becoming PhD proof.
        programme_page = bool(
            any(re.fullmatch(r"\s*Economics\s*", heading, re.I)
                for heading in parser.headings)
            and re.search(
                r"\bDegrees Offered\s+Doctor of Philosophy"
                r"\s*\(\s*Ph\.?D\.?\s*\)\s+Deadline\b",
                text, re.I,
            )
            and re.search(r"\bApplication Deadline\b", text, re.I)
        )
    # An official departmental host can supply subject identity even if the
    # page's H1 is generic and its specific PhD heading is H2/H3/H4.
    host = (
        (urllib.parse.urlsplit(source_url or "").hostname or "")
        .lower().removeprefix("www.")
    )
    if not programme_page:
        economics_host = host.split(".")[0] in {"economics", "econ"}
        programme_page = bool(
            economics_host and (
                any(
                    re.search(r"\b(?:ph\.?d\.?|doctoral)\b", heading, re.I)
                    for tag, heading in parser.tagged_blocks
                    if tag in {"h1", "h2", "h3", "h4"}
                )
                or PROGRAMME.search(text[:2000])
            )
        )
    # Some departments use a generic "Graduate Program" H1 but have an
    # institution-authored Economics department marker, a doctoral-programme
    # link, and an explicit "How to Apply" section. Allow that only on the
    # department's own /econ/graduate/apply or /admissions path.
    departmental_route = False
    if not programme_page and source_url:
        path = urllib.parse.urlsplit(source_url).path.lower()
        departmental_route = bool(
            re.search(
                r"/(?:eco|econ|economics)/graduate/"
                r"(?:[^/]+/)*(?:apply|applying|admissions?)(?:[./]|$)",
                path,
            )
            and re.search(r"\bdepartment of economics\b", text, re.I)
            and any(
                re.fullmatch(r"\s*Ph\.?D\.?\s+Program(?:me)?\s*", label, re.I)
                for _url, label in parser.links
            )
            and any(
                tag in {"h2", "h3", "h4"}
                and re.search(r"\b(?:apply|applying|how and when to apply)\b", heading, re.I)
                for tag, heading in parser.tagged_blocks
            )
            and not any(
                re.search(r"\b(?:master(?:'?s)?|mba|undergraduate)\b", heading, re.I)
                for tag, heading in parser.tagged_blocks
                if tag in {"h1", "h2", "h3", "h4"}
            )
        )
        programme_page = departmental_route
    if not programme_page:
        # A Master's-stage entry requires the university to spell out the
        # first-year economics doctorate linkage, not just "PhD Track".
        programme_page = bool(
            any(re.search(r"\bphd[\s-]+track\s+program(?:me)?\b", h, re.I)
                for h in parser.headings)
            and re.search(
                r"\bfirst year of (?:the )?PhD in Economics\b",
                text[:3000], re.I,
            )
        )
    candidates = _structured_deadline_candidates(
        parser, now=now, programme_page=programme_page,
    )
    for match in DATE_PATTERN.finditer(text):
        day = _parse_date(match)
        if day is None or not (now.date() <= day <= date(now.year + 2, 12, 31)):
            continue
        # A university may put a dated financial-support priority next to
        # the final application date under "PhD Application Deadlines".
        # Do not treat the support-only priority as a competing application
        # cutoff, even when the heading contains the word "deadline".
        if any(
            match.group() in block
            and re.search(
                r"^\s*(?:priority\s+)?(?:financial\s+(?:support|aid)|"
                r"funding|scholarships?|fellowships?)(?:\s+deadline)?\s*:",
                block, re.I,
            )
            for block in parser.blocks
        ):
            continue
        # A PhD navigation link cannot turn a separate Master's, MBA or
        # undergraduate application paragraph into a doctoral deadline.
        if departmental_route and any(
            match.group() in block
            and re.search(r"\b(?:master(?:'?s)?|mba|undergraduate)\b", block, re.I)
            for block in parser.blocks
        ):
            continue
        before = text[max(0, match.start() - 310):match.start()]
        deadlines = list(DEADLINE.finditer(before))
        if not deadlines:
            continue
        deadline = deadlines[-1]
        gap = before[deadline.end():]
        # Universities sometimes write "application deadline to the <named
        # Economics PhD programme> for the autumn intake is <DATE>".
        # This ties the longer gap to the actual programme and deadline;
        # it does not permit unrelated sessions, documents or awards.
        long_form = (
            65 < len(gap) <= 190
            and re.fullmatch(r"\s+(?:to|for)\s+.+\bis\s*", gap, flags=re.I | re.S)
            is not None
            and PROGRAMME.search(gap) is not None
            and ANCILLARY.search(gap) is None
        )
        if len(gap) > 65 and not long_form:
            continue
        # A test or supporting-document cutoff is not the application cutoff.
        qualifier = before[max(0, deadline.start() - 38):deadline.end()]
        if ANCILLARY.search(qualifier):
            continue
        # Generic closing/through/no-later-than wording is eligible only
        # when the surrounding sentence explicitly concerns an application.
        # In particular "open through the portal on DATE" is not a cutoff.
        label = deadline.group().lower()
        context = before[max(0, deadline.start() - 165):deadline.start()]
        if label.startswith(("close", "closing")):
            if not re.search(r"\bapplications?\b", context, re.I):
                continue
        elif label == "no later than":
            if not (
                re.search(r"\bapplications?\b", context, re.I)
                and re.search(r"\b(?:submit|submitted|received|due)\b", context, re.I)
            ):
                continue
        elif label == "through" and not (
            re.search(r"\bapplication\b", context, re.I)
            and re.search(r"\bavailable\b", context, re.I)
            and not re.search(r"\bopen\s+through\b", before[-45:], re.I)
        ):
            continue
        if not programme_page and not long_form:
            # Adjacent departmental introductions sometimes precede an
            # explicitly identified application window by one paragraph.
            # Only applications with their own closing language may use
            # this longer distance, not arbitrary dates.
            is_application_cutoff = bool(
                label == "through"
                or re.search(r"\bthe application deadline\b", before[-125:], re.I)
            )
            max_scope_gap = 300 if is_application_cutoff else 165
            programmes_before = [
                p for p in PROGRAMME.finditer(before)
                if p.end() <= deadline.start()
                and deadline.start() - p.end() <= max_scope_gap
            ]
            # Official pages also state "application deadline for the
            # Economics PhD is DATE" under a generic application heading.
            programmes_after = list(PROGRAMME.finditer(gap))
            if not programmes_before and not programmes_after:
                continue
        excerpt = text[max(0, match.start() - 115):min(len(text), match.end() + 20)]
        candidates.append((day.isoformat(), excerpt.strip()))
    distinct = {day for day, _ in candidates}
    if len(distinct) > 1:
        return "ambiguous_deadline", None, None
    if len(distinct) == 1:
        day, excerpt = candidates[0]
        return "verified", day, excerpt[:180]
    return "no_explicit_deadline", None, None




# Generic (e.g. .eu, .org) university domains do not independently prove
# where a programme is based. A university's own mailing address can supply
# a separately cited country fact, never the upstream lead's country alone.
OFFICIAL_COUNTRY_NAMES = (
    "Austria", "Australia", "Belgium", "Canada", "Switzerland",
    "Chile", "China", "Czechia", "Germany", "Denmark", "Spain",
    "Finland", "France", "Greece", "Hong Kong", "Ireland", "Italy",
    "Japan", "South Korea", "Malaysia", "Netherlands", "Norway",
    "New Zealand", "Philippines", "Poland", "Portugal", "Serbia",
    "Sweden", "Singapore", "Thailand", "Taiwan", "United Kingdom",
    "United States", "South Africa",
)
OFFICIAL_COUNTRY_WORD = re.compile(
    r"\b(?:" + "|".join(
        re.escape(country) for country in OFFICIAL_COUNTRY_NAMES
    ) + r")\b", re.I,
)
ADDRESS_LABEL = re.compile(
    r"\b(?:mailing|postal|campus|institutional)\s+address\b", re.I,
)


def extract_official_country(
    html: str, *, evidence_url: str, checked_at: datetime,
) -> dict[str, str] | None:
    """Use an institutional address, never general country or travel mentions.

    Multiple different countries in contact/address evidence are ambiguous.
    The source, exact excerpt and check time remain available for auditing.
    """
    parser = PageText()
    parser.feed(html[:MAX_HTML_BYTES])
    blocks = parser.blocks
    candidates: list[str] = list(parser.address_blocks)
    for index, block in enumerate(blocks):
        if ADDRESS_LABEL.search(block):
            candidates.extend(blocks[index + 1:index + 4])
        elif re.search(r"^\s*(?:mailing|postal)\s+address\s*:", block, re.I):
            candidates.append(block)
    # Some university footers publish their *institutional mailing address*
    # as raw footer text rather than a <p> or <address> element. Require a
    # copyright marker, a street indicator and a postal code together:
    # "Time in Italy" or generic study-abroad mentions do not qualify.
    tail = parser.text()[-1600:]
    marker = tail.rfind("©")
    if marker >= 0:
        footer_address = tail[marker:marker + 220]
        if (
            re.search(r"\b(?:Via|Street|Road|Avenue|Carrer)\b",
                      footer_address, re.I)
            and re.search(r"\b(?:[A-Z]-)?\d{4,5}\b", footer_address)
        ):
            candidates.append(footer_address)
    found: dict[str, str] = {}
    for address in candidates:
        matches = list(OFFICIAL_COUNTRY_WORD.finditer(address))
        for match in matches:
            name = next(
                (item for item in OFFICIAL_COUNTRY_NAMES
                 if item.casefold() == match.group().casefold()),
                None,
            )
            if name is not None:
                found[name] = " ".join(address.split())[:220]
    if len(found) != 1:
        return None
    name, excerpt = next(iter(found.items()))
    return {
        "value": name, "evidence_url": evidence_url,
        "evidence_excerpt": excerpt,
        "checked_at": checked_at.isoformat(
            timespec="seconds",
        ).replace("+00:00", "Z"),
    }



def extract_official_details(
    html: str, *, evidence_url: str, checked_at: datetime,
) -> dict[str, dict[str, str]]:
    """Conservative programme facts; every field retains its source and timestamp."""
    parser = PageText()
    parser.feed(html[:MAX_HTML_BYTES])
    if PROGRAMME.search(parser.text()[:7000]) is None:
        return {}
    blocks = parser.blocks or [parser.text()[:MAX_HTML_BYTES]]
    stamp = checked_at.isoformat(timespec="seconds").replace("+00:00", "Z")
    facts: dict[str, dict[str, str]] = {}

    def add(key: str, value: str, excerpt: str) -> None:
        value = " ".join(value.split())[:175]
        excerpt = " ".join(excerpt.split())[:220]
        if value and excerpt:
            item = {
                "value": value, "evidence_url": evidence_url,
                "evidence_excerpt": excerpt, "checked_at": stamp,
            }
            if key not in facts or facts[key]["value"] == value:
                facts[key] = item

    for index, block in enumerate(blocks):
        following = blocks[index + 1] if index + 1 < len(blocks) else ""
        if (
            re.fullmatch(
                r"(?:language(?: of instruction)?|teaching language)\s*:?",
                block, re.I,
            )
            and re.fullmatch(
                r"English|German|French|Spanish|Finnish|Swedish", following, re.I,
            )
        ):
            add("language", following, block + " " + following)
        if re.fullmatch(r"(?:duration|study duration)\s*:?", block, re.I):
            m = re.fullmatch(
                r"(\d{1,2})\s+years?(?:\s*,?\s*(full[- ]time|part[- ]time))?",
                following, re.I,
            )
            if m:
                years = m.group(1)
                value = years + (" year" if years == "1" else " years")
                if m.group(2):
                    value += ", " + m.group(2).lower().replace("full time", "full-time")
                add("duration", value, block + " " + following)
        if (
            re.fullmatch(r"(?:eligibility|entry requirements?)\s*:?", block, re.I)
            and re.search(
                r"\b(?:master(?:'s|’s)?|bachelor(?:'s|’s)?|"
                r"university\s+degree|higher\s+education\s+degree)\b",
                following, re.I,
            )
            and not re.search(
                r"\b(?:cannot\s+confirm|outside\s+the\s+actual\s+application|"
                r"assessed\s+based\s+on\s+documents)\b", following, re.I,
            )
        ):
            add("entry_requirement", following, block + " " + following)
        if re.search(r"\b(?:no tuition fees|free of tuition fees)\b", block, re.I):
            add("tuition", "No tuition fees", block)
        if re.search(r"\bapplicants?\s+should\s+have\s+a\s+master", block, re.I):
            add("entry_requirement", block, block)
        opening = re.search(
            r"\bapplication\s+(?:period\s+)?opens?\s+on\s+", block, re.I,
        )
        if opening:
            m = DATE_PATTERN.search(block, opening.end())
            if m and m.start() - opening.end() < 12:
                day = _parse_date(m)
                if day and checked_at.date() <= day <= date(checked_at.year + 2, 12, 31):
                    add("application_open_iso", day.isoformat(), block)
        stipend = re.search(
            r"\bmonthly\s+stipend\s+of\s+([\d,]+)\s*(?:Euros?|EUR|€)\b",
            block, re.I,
        )
        if stipend and re.search(r"\bqualification\s+phase\b", block, re.I):
            add("stipend", f"€{stipend.group(1)}/month (qualification phase)", block)
        semester = re.search(
            r"\bsemester\s+fee\s+of\s+(approximately\s+)?"
            r"([\d,]+\s*[-–]\s*[\d,]+)\s*€",
            block, re.I,
        )
        if semester:
            amount = re.sub(r"\s*[-–]\s*", "–", semester.group(2))
            qualifier = " (approx.)" if semester.group(1) else ""
            add("semester_fee", f"€{amount}/semester{qualifier}", block)
        if (
            re.search(r"\b(?:GRE|GMAT)\b", block, re.I)
            and re.search(r"\bnot\s+mandatory\b", block, re.I)
            and re.search(r"\brecommended\b", block, re.I)
        ):
            names = [name for name in ("GRE", "GMAT") if name in block.upper()]
            add("tests", "/".join(names) + ": recommended, not mandatory", block)
        if re.search(r"\b(?:two|2)\s+academic\s+reference\s+letters?\b", block, re.I):
            add("references", "Two academic reference letters", block)

    # A Master's first-year entry is eligible as a PhD track ONLY when the
    # university explicitly identifies it as Year 1 of an Economics PhD.
    # The discovery list's "Master's + PhD" hint is not supporting evidence.
    if "/masters-degrees/" in urllib.parse.urlsplit(evidence_url).path:
        for block in blocks:
            if re.search(
                r"\b(?:first year|year\s*1)\s+of\s+(?:the\s+)?"
                r"PhD\s+in\s+Economics\b",
                block, re.I,
            ):
                add(
                    "admission_route",
                    "PhD track — first-year Master's-stage entry",
                    block,
                )
                break

    # The BSE/UPF first PhD-track year uses a Master's application portal.
    # Do not inherit zero-tuition assumptions from *other* direct doctorates:
    # retain a specific first-year fee and optional merit support only when
    # the official doctoral-track page states them explicitly.
    track_page = (
        "/masters-degrees/" in urllib.parse.urlsplit(evidence_url).path
        and "admission_route" in facts
    )
    if track_page:
        for index, block in enumerate(blocks):
            fee = re.search(
                r"\bstudent\s+fee\s*:\s*€\s*([\d,]+)\b", block, re.I,
            )
            if fee:
                add("tuition", f"€{fee.group(1)} (first-year programme fee)", block)
            if (
                re.search(r"\bGRE\s+score\s+is\s+required\b", block, re.I)
                and re.search(
                    r"\bPhD[\s-]+track\b",
                    " ".join(blocks[max(0, index - 2):index + 1]), re.I,
                )
            ):
                add("tests", "GRE required for PhD-track entry", block)
            if re.search(
                r"\bfunding\s+opportunities\b.*\bawarded\s+on\s+the\s+basis\s+of"
                r"\s+academic\s+excellence\b", block, re.I,
            ):
                add(
                    "funding_note",
                    "Merit-based support; award not guaranteed (first-year PhD track)",
                    block,
                )

    # Select the *specific funding sentence*, not the first 175 characters
    # of a long paragraph that may omit later dissertation-phase conditions.
    sentences = [
        sentence.strip()
        for block in blocks
        for sentence in re.split(r"(?<=[.!?])\s+", block)
    ]
    funding = [
        sentence for sentence in sentences
        if re.search(r"\bfunding\b", sentence, re.I)
        and re.search(
            r"\b(?:first\s+(?:two|2)\s+years?|first\s+study\s+year|"
            r"expected\s+length|conditional\s+on|performance\s+criteria)\b",
            sentence, re.I,
        )
    ]
    if funding:
        qualified = [sentence for sentence in funding if "conditional" in sentence.lower()]
        chosen = (qualified or funding)[0]
        add("funding_note", chosen, chosen)

    # Some official sites print structured labels directly inside DIVs.
    # Accept a tightly adjacent label/value only on a programme-specific H1.
    if any(PROGRAMME.search(heading) for heading in parser.headings):
        full_text = parser.text()
        if "language" not in facts:
            language = re.search(
                r"\blanguage\s+of\s+instruction\s*:\s*"
                r"(English|German|French|Spanish|Finnish|Swedish)\b",
                full_text, re.I,
            )
            if language:
                add("language", language.group(1), language.group())
        if "duration" not in facts:
            duration = re.search(
                r"\bduration\s*:\s*(\d{1,2})\s+years?"
                r"(?:\s*,?\s*(full[- ]time|part[- ]time))?\b",
                full_text, re.I,
            )
            if duration:
                years = duration.group(1)
                value = years + (" year" if years == "1" else " years")
                if duration.group(2):
                    value += ", " + duration.group(2).lower()
                    value = value.replace("full time", "full-time")
                add("duration", value, duration.group())
    return facts


_LINK_RELEVANCE = re.compile(
    r"\b(?:admissions?|applications?|apply|deadlines?|"
    r"fees|funding|scholarships?|eligibility|requirements?)\b", re.I,
)
_LINK_SKIP = re.compile(
    r"\.(?:pdf|docx?|xlsx?|zip|png|jpe?g)(?:$|\?)|"
    r"/(?:login|log-in|signin|sign-in|signup|register|logout|"
    r"account|captcha|search|api|job-market|about-us|"
    r"alumni|faculty|events?|news|press)(?:/|$|\?)|"
    r"\b(?:authenticity-of-documents|job-market-candidates)\b", re.I,
)


def _institutional_url(
    raw: str, root_url: str, *, for_provenance: bool = False,
) -> str | None:
    try:
        root = urllib.parse.urlsplit(root_url)
        resolved = urllib.parse.urlsplit(urllib.parse.urljoin(root_url, raw))
        host = (resolved.hostname or "").lower().removeprefix("www.")
        root_host = (root.hostname or "").lower().removeprefix("www.")
        port = resolved.port
    except ValueError:
        return None
    if (
        resolved.scheme != "https" or host != root_host
        or resolved.username is not None or resolved.password is not None
        or port not in (None, 443) or not resolved.path.startswith("/")
        or (not for_provenance and _LINK_SKIP.search(resolved.path))
        or len(resolved.query) > 128
    ):
        return None
    return urllib.parse.urlunsplit(
        (resolved.scheme, resolved.netloc, resolved.path, resolved.query, "")
    )


def select_official_links(
    html: str, source_url: str, *, max_links: int = 2,
) -> list[str]:
    """Prioritise relevant same-host HTML pages, never portals or aggregators."""
    if not 0 <= max_links <= 4:
        raise ValueError("max_links must be 0..4")
    parser = PageText()
    parser.feed(html[:MAX_HTML_BYTES])
    scores: dict[str, int] = {}
    for href, label in parser.links[:300]:
        candidate = _institutional_url(href, source_url)
        if not candidate or candidate == source_url:
            continue
        blob = f"{label} {urllib.parse.urlsplit(candidate).path.replace('-', ' ')}"
        if not _LINK_RELEVANCE.search(blob):
            continue
        score = 1
        if re.search(r"admissions?|applications?|deadlines?|apply", blob, re.I):
            score += 3
        if re.search(r"economics?|phd|doctoral", blob, re.I):
            score += 4
        if re.search(r"fees|funding", blob, re.I):
            score += 2
        # A generic undergraduate/MBAs admissions link must not consume
        # one of the two university-page visits ahead of a doctoral route.
        if re.search(
            r"\b(?:undergraduate|bachelor|mba|executive|alumni)\b", blob, re.I,
        ):
            score -= 9
        if re.search(r"\b(?:phd|doctoral|doctorate)\b", blob, re.I):
            score += 6
        if score <= 0:
            continue
        if candidate not in scores or score > scores[candidate]:
            scores[candidate] = score
    return sorted(scores, key=lambda url: (-scores[url], url))[:max_links]



def select_official_contact_link(html: str, source_url: str) -> str | None:
    """Select a documented same-host contact page for address verification."""
    parser = PageText()
    parser.feed(html[:MAX_HTML_BYTES])
    links = parser.links[:300] + parser.links[-150:]
    for href, label in links:
        candidate = _institutional_url(href, source_url)
        if candidate is None:
            continue
        path = urllib.parse.urlsplit(candidate).path.rstrip("/").lower()
        if (
            re.fullmatch(r"/(?:(?:en|eng)/)?(?:contact|contacts|contact-us)", path)
            and re.search(r"\bcontact\b", label, re.I)
        ):
            return candidate
    return None


def investigate_official_pages(
    official_url: str, *, now: datetime, fetch_html,
    robots_allowed, max_pages: int = 3,
) -> dict:
    """Bounded same-host research; callbacks are mocked in offline tests."""
    if not 1 <= max_pages <= 4:
        raise ValueError("max_pages must be 1..4")
    root = urllib.parse.urlsplit(official_url)
    empty = {
        "deadline_iso": None, "evidence_url": None, "evidence_excerpt": None,
        "official_details": {}, "investigated_urls": [],
    }
    if root.scheme != "https" or not root.hostname:
        return {"status": "insecure_source", **empty}
    queue = [official_url]
    seen: set[str] = set()
    investigated: list[str] = []
    dates: list[tuple[str, str, str]] = []
    masters_stage_dates: list[tuple[str, str, str]] = []
    details: dict[str, dict[str, str]] = {}
    conflicts: set[str] = set()
    ambiguous = False
    first_error: str | None = None
    while queue and len(seen) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        if _institutional_url(url, official_url) is None:
            first_error = first_error or "unsafe_redirect"
            continue
        if not robots_allowed(url):
            first_error = first_error or "robots_disallowed"
            continue
        try:
            html, final_url = fetch_html(url)
        except (OSError, TimeoutError, ValueError, UnicodeError):
            first_error = first_error or "fetch_failed"
            continue
        if _institutional_url(final_url, official_url) is None:
            first_error = first_error or "unsafe_redirect"
            continue
        # A nominal HTTP 200 can be a university login/CAPTCHA page
        # containing plausible dates. It is not successful source evidence,
        # including for injected offline fetchers and linked admissions pages.
        if official_html_response_problem(html, max_bytes=MAX_HTML_BYTES) is not None:
            first_error = first_error or "fetch_failed"
            continue
        investigated.append(final_url)
        status, day, excerpt = collect_official_deadline(
            html, now=now, source_url=final_url,
        )
        page_parser = PageText()
        page_parser.feed(html[:MAX_HTML_BYTES])
        masters_admissions = any(
            re.search(r"\badmissions?\b", heading, re.I)
            and re.search(r"\bmaster(?:'?s|’s)?\s+degrees?\b", heading, re.I)
            for heading in page_parser.headings
        )
        if masters_admissions:
            # A university's Master's admission date is NOT automatically a
            # doctorate application deadline. Only its explicit, adjacent
            # "Application deadline: <full year>" dates are candidates;
            # even those need an independently corroborated PhD-track route.
            stage_candidates: list[tuple[str, str, str]] = []
            track_named = re.search(
                r"\bPhD[\s-]+Track\s+Program(?:me)?\b",
                page_parser.text()[:14000], re.I,
            )
            if track_named:
                for block in page_parser.blocks:
                    label = re.search(
                        r"\b(?:first\s+round\s+)?application\s+deadline\s*:\s*",
                        block, re.I,
                    )
                    if not label:
                        continue
                    match = DATE_PATTERN.search(block, label.end())
                    if not match or match.start() - label.end() > 15:
                        continue
                    proposed = _parse_date(match)
                    if proposed and now.date() <= proposed <= date(
                        now.year + 2, 12, 31,
                    ):
                        stage_candidates.append(
                            (proposed.isoformat(), final_url, block[:180]),
                        )
            if len({date_iso for date_iso, _, _ in stage_candidates}) > 1:
                ambiguous = True
            else:
                masters_stage_dates.extend(stage_candidates)
        elif status == "ambiguous_deadline":
            ambiguous = True
        elif status == "verified" and day and excerpt:
            dates.append((day, final_url, excerpt))
        page_facts = extract_official_details(
            html, evidence_url=final_url, checked_at=now,
        )
        country_fact = extract_official_country(
            html, evidence_url=final_url, checked_at=now,
        )
        if country_fact is not None:
            page_facts["institution_country"] = country_fact
        for field, fact in page_facts.items():
            if field in conflicts:
                continue
            previous = details.get(field)
            if previous and previous["value"] != fact["value"]:
                details.pop(field)
                conflicts.add(field)
            elif previous is None:
                details[field] = fact
        if len(seen) + len(queue) < max_pages:
            # A generic university domain (.eu, .org, ...) does not itself
            # certify the country. Dedicate one *bounded, robots-aware*
            # follow-up to a linked institutional contact address if needed.
            generic = (
                (urllib.parse.urlsplit(official_url).hostname or "")
                .lower().split(".")[-1]
                in {"eu", "org", "com", "net", "edu", "int"}
            )
            if generic and "institution_country" not in details and len(seen) == 1:
                contact = select_official_contact_link(html, final_url)
                if contact and contact not in seen and contact not in queue:
                    queue.append(contact)
            more = select_official_links(
                html, final_url, max_links=max_pages - len(seen) - len(queue),
            )
            for candidate in more:
                if candidate not in seen and candidate not in queue:
                    queue.append(candidate)
    # Only promote a Master's-stage application date when a separate official
    # PhD Track programme page established the first-year doctoral linkage.
    if "admission_route" in details:
        dates.extend(masters_stage_dates)
    distinct = {day for day, _, _ in dates}
    if ambiguous or len(distinct) > 1:
        status = "ambiguous_deadline"
    elif len(distinct) == 1:
        status = "verified"
    elif investigated:
        status = "no_explicit_deadline"
    else:
        status = first_error or "fetch_failed"
    chosen = dates[0] if status == "verified" else None
    return {
        "status": status,
        "deadline_iso": chosen[0] if chosen else None,
        "evidence_url": chosen[1] if chosen else None,
        "evidence_excerpt": chosen[2] if chosen else None,
        "official_details": details,
        "investigated_urls": investigated,
    }

def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except ValueError:
        return None


def eligible_for_check(entry: dict, *, now: datetime) -> bool:
    checked = _timestamp(entry.get("checked_at"))
    return checked is None or checked > now or now - checked >= CHECK_INTERVAL


def _key(item: dict) -> tuple[str, str]:
    return item["institution"], item["country_code"]


def validate_catalogues(seeds: dict, public: dict) -> None:
    if seeds.get("kind") != "economics_phd_admissions_seeds":
        raise ValueError("Unexpected seed type")
    if public.get("kind") != "economics_phd_admissions_observations":
        raise ValueError("Unexpected public catalogue type")
    if public.get("scope") != "official_programme_sources_only":
        raise ValueError("Public observations must be official-source only")
    if public.get("source", {}).get("deadline_values_reused") is not False:
        raise ValueError("Upstream dates must never be reused")
    rows = seeds.get("programmes")
    observations = public.get("programmes")
    if not isinstance(rows, list) or len(rows) != 251:
        raise ValueError("Unexpected seed count")
    if not isinstance(observations, list) or len(observations) != len(rows):
        raise ValueError("Unexpected public count")
    if len({_key(r) for r in rows}) != len(rows):
        raise ValueError("Duplicate seeds")
    if [_key(r) for r in rows] != [_key(r) for r in observations]:
        raise ValueError("Seed/observation ordering mismatch")
    for seed, observation in zip(rows, observations, strict=True):
        if not isinstance(seed.get("institution"), str) or not isinstance(
            seed.get("country_code"), str
        ):
            raise ValueError("Invalid programme")
        if not re.fullmatch(r"[A-Z]{2}", seed["country_code"]):
            raise ValueError("Invalid country code")
        if any(k in seed for k in ("deadline", "deadline_guidance", "deadline_iso")):
            raise ValueError("Unverified upstream deadline in seeds")
        url = seed.get("official_programme_url")
        if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme not in {"https", "http"}:
            raise ValueError("Invalid institutional lead")
        if observation.get("official_programme_url") != url:
            raise ValueError("Source URLs must not be overwritten")
        if observation.get("status") not in STATUSES:
            raise ValueError("Unknown verification state")
        if "deadline_guidance" in observation or "published" in observation:
            raise ValueError("Upstream/reference values leaked")
        urls = observation.get("investigated_urls", [])
        if not isinstance(urls, list) or len(urls) > 4:
            raise ValueError("Unbounded programme source provenance")
        if any(
            not isinstance(source, str) or _institutional_url(
                source, url, for_provenance=True,
            ) is None
            for source in urls
        ):
            raise ValueError("Programme provenance must stay on institutional host")
        fields = observation.get("official_details", {})
        if not isinstance(fields, dict):
            raise ValueError("Malformed official programme facts")
        allowed_fields = {
            "language", "duration", "entry_requirement", "tuition",
            "application_open_iso", "stipend", "semester_fee", "tests",
            "references", "funding_note", "admission_route",
            "institution_country",
        }
        if fields.keys() - allowed_fields:
            raise ValueError("Unsupported official programme fact")
        for item in fields.values():
            if not isinstance(item, dict) or any(
                not isinstance(item.get(k), str) or not item[k].strip()
                for k in ("value", "evidence_url", "evidence_excerpt", "checked_at")
            ):
                raise ValueError("Missing field-level official evidence")
            if len(item["value"]) > 175 or len(item["evidence_excerpt"]) > 220:
                raise ValueError("Oversized field evidence")
            if _institutional_url(
                item["evidence_url"], url, for_provenance=True,
            ) is None:
                raise ValueError("External programme evidence is forbidden")
            if urls and item["evidence_url"] not in urls:
                raise ValueError("Field evidence was not investigated")
            if item["checked_at"] != observation.get("checked_at"):
                raise ValueError("Field evidence must be from current source check")
        if observation["status"] == "verified":
            dt = observation.get("deadline_iso")
            if not isinstance(dt, str):
                raise ValueError("Invalid verified deadline")
            try:
                date.fromisoformat(dt)
            except ValueError as exc:
                raise ValueError("Malformed verified deadline") from exc
            if not observation.get("evidence_url") or not observation.get("evidence_excerpt"):
                raise ValueError("Verified dates require official evidence")
        elif observation.get("deadline_iso") is not None:
            raise ValueError("Unverified deadline must not be published")


class OfficialOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(
        self, allowed_host: str,
        robots_allowed: Callable[[str], bool] | None = None,
    ) -> None:
        self.allowed_host = allowed_host.lower().removeprefix("www.")
        self.robots_allowed = robots_allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if parsed.scheme != "https" or host != self.allowed_host:
            raise ValueError("unsafe_redirect")
        # urllib follows redirects without re-entering our outer verifier.
        # Inspect the destination BEFORE urllib fetches it, including when
        # the source path was permitted but the redirected path is blocked.
        if self.robots_allowed is not None and not self.robots_allowed(newurl):
            raise ValueError("robots_disallowed_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read_url(
    url: str, *, host: str, limit: int,
    allowed_redirect: Callable[[str], bool] | None = None,
) -> tuple[int, bytes, str]:
    opener = urllib.request.build_opener(
        OfficialOnlyRedirect(host, robots_allowed=allowed_redirect),
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with opener.open(req, timeout=9) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("response_too_large")
        return response.status, data, response.geturl()


def check_official_url(url: str, *, now: datetime) -> dict:
    """Robots-aware bounded institutional research (no cross-domain crawling)."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return {"status": "insecure_source"}
    host = parsed.hostname
    robots_url = f"https://{host}/robots.txt"
    robot = urllib.robotparser.RobotFileParser()
    robot.set_url(robots_url)
    try:
        status, data, final_robots_url = _read_url(
            robots_url, host=host, limit=MAX_ROBOTS_BYTES,
            allowed_redirect=lambda _destination: False,
        )
        if status != 200 or final_robots_url != robots_url:
            raise ValueError("unsafe_robots_response")
        parse_official_robots(data, robot)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            robot.allow_all = True
        else:
            return {"status": "robots_unavailable"}
    except (OSError, TimeoutError, ValueError, UnicodeError):
        return {"status": "robots_unavailable"}

    def allowed(page_url: str) -> bool:
        return robot.can_fetch(USER_AGENT, page_url)

    def fetch_page(page_url: str) -> tuple[str, str]:
        status, data, final_url = _read_url(
            page_url, host=host, limit=MAX_HTML_BYTES,
            allowed_redirect=allowed,
        )
        if status != 200 or data.lstrip().startswith(b"%PDF"):
            raise ValueError("unsupported official source response")
        return data.decode("utf-8", errors="replace"), final_url

    suffix = host.lower().split(".")[-1]
    # Preserve two admissions links; allow one additional official address
    # page only where the domain suffix cannot independently prove location.
    page_budget = 4 if suffix in {"eu", "org", "com", "net", "edu", "int"} else 3
    return investigate_official_pages(
        url, now=now, fetch_html=fetch_page, robots_allowed=allowed,
        max_pages=page_budget,
    )

def refresh(seeds: dict, public: dict, *, now: datetime, batch_size: int,
            recheck_no_explicit: bool = False, fetcher=check_official_url,
            selected_indices: list[int] | None = None) -> dict:
    if batch_size < 1 or batch_size > 40:
        raise ValueError("batch_size must be 1..40")
    validate_catalogues(seeds, public)
    programmes = [dict(item) for item in public["programmes"]]
    # Always check never-visited programmes before revisiting previous sources.
    # An absent GitHub schedule must not strand a calendar shard for 11 days.
    def priority(index: int) -> tuple[datetime, int]:
        checked = _timestamp(programmes[index].get("checked_at"))
        return checked or datetime.min.replace(tzinfo=UTC), index

    # A trusted parser-source change may correct earlier "no date found"
    # results even while they are younger than the 11-day interval. Retry
    # only successfully read but inconclusive sources, never robots-blocked
    # or failed/restricted providers.
    readable_negatives = sorted(
        (i for i, item in enumerate(programmes)
         if recheck_no_explicit
         and item.get("status") in {"no_explicit_deadline", "ambiguous_deadline"}
         and _timestamp(item.get("checked_at")) is not None),
        key=priority,
    )
    # Trusted checker updates may change the interpretation of *previously*
    # extracted facts (e.g. a conditional funding statement). Refresh all
    # already-verified programme observations in the bounded push-triggered
    # batch, including existing detail fields, without promoting upstream data.
    # Scheduled refreshes preserve the normal 11-day cadence.
    needs_details = sorted(
        (i for i, item in enumerate(programmes)
         if recheck_no_explicit and item.get("status") == "verified"
         and i not in readable_negatives),
        key=priority,
    )
    rechecking = set(readable_negatives + needs_details)
    revision_misses = sorted(
        (i for i, item in enumerate(programmes)
         if i not in rechecking
         and item.get("status") in {"no_explicit_deadline", "ambiguous_deadline"}
         and item.get("extractor_revision") != EXTRACTOR_REVISION
         and _timestamp(item.get("checked_at")) is not None),
        key=priority,
    )
    rechecking.update(revision_misses)
    # Newly adopted/remediated official programme leads must not wait behind
    # a large backlog of readable negatives awaiting an extractor upgrade.
    unvisited = sorted(
        (i for i, item in enumerate(programmes)
         if i not in rechecking and item.get("status") == "unverified"
         and _timestamp(item.get("checked_at")) is None),
        key=priority,
    )
    due = sorted(
        (i for i, item in enumerate(programmes)
         if i not in rechecking and i not in unvisited
         and eligible_for_check(item, now=now)),
        key=priority,
    )
    selected = set(
        (needs_details + readable_negatives + unvisited + revision_misses + due)
        [:batch_size]
    )
    if selected_indices is not None:
        if (
            len(selected_indices) > batch_size
            or len(selected_indices) != len(set(selected_indices))
            or any(not isinstance(i, int) or not 0 <= i < len(programmes)
                   for i in selected_indices)
        ):
            raise ValueError("Invalid bounded source selection")
        selected = set(selected_indices)
    stamp = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    for index, entry in enumerate(programmes):
        old = _timestamp(entry.get("checked_at"))
        if entry.get("status") == "verified" and (
            old is None or now - old > EXPIRY or
            entry.get("deadline_iso", "") < now.date().isoformat()
        ):
            entry.update(
                status="stale", deadline_iso=None, evidence_url=None,
                evidence_excerpt=None, official_details={}, investigated_urls=[],
            )
        if old and now - old > EXPIRY:
            entry.update(official_details={}, investigated_urls=[])
        if index not in selected:
            continue
        result = fetcher(entry["official_programme_url"], now=now)
        status = result.get("status")
        if status not in STATUSES - {"unverified", "stale"}:
            raise ValueError("Untrusted verifier status")
        entry.update(
            status=status, checked_at=stamp, deadline_iso=None,
            extractor_revision=EXTRACTOR_REVISION,
            evidence_url=None, evidence_excerpt=None,
            official_details=result.get("official_details") or {},
            investigated_urls=result.get("investigated_urls") or [],
        )
        if status == "verified":
            entry.update(deadline_iso=result["deadline_iso"],
                         evidence_url=result["evidence_url"],
                         evidence_excerpt=result["evidence_excerpt"])
    result = dict(public)
    result["generated_at"] = stamp
    result["programmes"] = programmes
    validate_catalogues(seeds, result)
    return result


def refresh_inconclusive(
    seeds: dict, public: dict, *, now: datetime, batch_size: int = 40,
    fetcher=check_official_url,
) -> dict:
    """Recheck all readable misses exactly once; never retry provider-blocked sources.

    Snapshot the cohort first: a successful recheck may promote one record.
    The bounded refresh function validates every successive batch. Regular
    scheduled runs retain their independent 25-source budget.
    """
    if not 1 <= batch_size <= 40:
        raise ValueError("batch_size must be 1..40")
    validate_catalogues(seeds, public)
    indices = [
        i for i, row in enumerate(public["programmes"])
        if row.get("status") == "no_explicit_deadline"
    ]
    updated = public
    for start in range(0, len(indices), batch_size):
        updated = refresh(
            seeds, updated, now=now, batch_size=batch_size, fetcher=fetcher,
            selected_indices=indices[start:start + batch_size],
        )
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate offline; never fetch")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument(
        "--recheck-all-readable", action="store_true",
        help="One-off review of every currently readable no-explicit-date source",
    )
    parser.add_argument(
        "--recheck-no-explicit", action="store_true",
        help="On trusted parser updates, retry accessible uncorroborated pages",
    )
    args = parser.parse_args(argv)
    seeds = json.loads(SEEDS.read_text(encoding="utf-8"))
    public = json.loads(PUBLIC.read_text(encoding="utf-8"))
    validate_catalogues(seeds, public)
    if args.check:
        print("PhD admissions: catalogue and provenance valid; network not used")
        return 0
    now = datetime.now(UTC)
    if args.recheck_all_readable:
        updated = refresh_inconclusive(
            seeds, public, now=now, batch_size=min(args.batch_size, 40),
        )
    else:
        updated = refresh(
            seeds, public, now=now, batch_size=args.batch_size,
            recheck_no_explicit=args.recheck_no_explicit,
        )
    PUBLIC.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    statuses: dict[str, int] = {}
    for entry in updated["programmes"]:
        statuses[entry["status"]] = statuses.get(entry["status"], 0) + 1
    print("Official-only PhD admissions rotation:", json.dumps(statuses, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
