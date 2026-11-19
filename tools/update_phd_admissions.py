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
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "config/phd_admissions_seeds.json"
PUBLIC = ROOT / "docs/data/phd_admissions.json"
USER_AGENT = "CollegeumAdmissionsMonitor/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
CHECK_INTERVAL = timedelta(days=11)
EXPIRY = timedelta(days=14)
MAX_HTML_BYTES = 1024 * 1024
MAX_ROBOTS_BYTES = 256 * 1024
DATE_PATTERN = re.compile(
    r"\b(?P<iso>20\d{2}-\d{2}-\d{2})\b|"
    r"\b(?P<day>\d{1,2})\s+(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s*,?\s*(?P<year>20\d{2})\b|"
    r"\b(?P<month2>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(?P<day2>\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(?P<year2>20\d{2})\b",
    re.I,
)
PROGRAMME = re.compile(
    r"(?:economics?\s+(?:ph\.?d\.?|doctor(?:al|ate))|"
    r"(?:ph\.?d\.?|doctor(?:al|ate))\s+(?:in\s+)?economics?|"
    r"(?:ph\.?d\.?|doctoral)\s+programmes?\s+in\s+[^.?!\n]{0,80}?\beconomics?)",
    re.I,
)
DEADLINE = re.compile(
    r"(?:application(?:s)?\s+)?deadlines?|"
    r"applications?\s+(?:close|due|must\s+be\s+submitted)|"
    r"apply\s+by|"
    r"submission\s+deadline|"
    r"closes?\s+on|closing\s+date",
    re.I,
)
# Explicitly exclude ancillary document, exam, funding and decision deadlines.
# Their dates can sit immediately beside the programme application deadline.
ANCILLARY = re.compile(
    r"\b(?:document|supporting|transcript|reference|recommendation|"
    r"language|test|gmat|gre|scholarship|appeal|decision|interview)\b",
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
        self._block_tag: str | None = None
        self._block_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h1":
            self._in_h1 = True
            self._heading_parts = []
        if (
            tag in {"h1", "h2", "h3", "h4", "p", "li", "dt", "dd", "th", "td"}
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
            self._block_tag = None
            self._block_parts = []
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


def collect_official_deadline(html: str, *, now: datetime) -> tuple[str, str | None, str | None]:
    """Extract only an explicit, unambiguous date near PhD economics context.

    No inference from month/day without a year, academic intake, an expired date,
    another subject, or an admissions aggregator is allowed.
    """
    parser = PageText()
    parser.feed(html[:MAX_HTML_BYTES])
    text = parser.text()[:MAX_HTML_BYTES]
    candidates: list[tuple[str, str]] = []
    # A specific programme H1 makes its admission schedule authoritative for
    # the page, while generic multi-programme pages still need nearby context.
    programme_page = any(PROGRAMME.search(heading) for heading in parser.headings)
    for match in DATE_PATTERN.finditer(text):
        day = _parse_date(match)
        if day is None or not (now.date() <= day <= date(now.year + 2, 12, 31)):
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
        # "Closes on" may describe many things; accept it only when a nearby
        # application period or application form is the stated subject.
        if deadline.group().lower().startswith(("close", "closing")):
            context = before[max(0, deadline.start() - 135):deadline.start()]
            if not re.search(r"\bapplications?\b", context, re.I):
                continue
        if not programme_page and not long_form:
            programmes = list(PROGRAMME.finditer(before))
            if not programmes:
                continue
            programme = programmes[-1]
            if programme.end() > deadline.start() or deadline.start() - programme.end() > 165:
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
            score += 2
        if re.search(r"fees|funding", blob, re.I):
            score += 3
        if candidate not in scores or score > scores[candidate]:
            scores[candidate] = score
    return sorted(scores, key=lambda url: (-scores[url], url))[:max_links]


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
        if not isinstance(html, str) or not html.lstrip().startswith("<"):
            first_error = first_error or "fetch_failed"
            continue
        investigated.append(final_url)
        status, day, excerpt = collect_official_deadline(html, now=now)
        if status == "ambiguous_deadline":
            ambiguous = True
        elif status == "verified" and day and excerpt:
            dates.append((day, final_url, excerpt))
        for field, fact in extract_official_details(
            html, evidence_url=final_url, checked_at=now,
        ).items():
            if field in conflicts:
                continue
            previous = details.get(field)
            if previous and previous["value"] != fact["value"]:
                details.pop(field)
                conflicts.add(field)
            elif previous is None:
                details[field] = fact
        if len(seen) + len(queue) < max_pages:
            more = select_official_links(
                html, final_url, max_links=max_pages - len(seen) - len(queue),
            )
            for candidate in more:
                if candidate not in seen and candidate not in queue:
                    queue.append(candidate)
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
            "references", "funding_note",
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
    def __init__(self, allowed_host: str) -> None:
        self.allowed_host = allowed_host.lower().removeprefix("www.")

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if parsed.scheme != "https" or host != self.allowed_host:
            raise ValueError("unsafe_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read_url(url: str, *, host: str, limit: int) -> tuple[int, bytes, str]:
    opener = urllib.request.build_opener(OfficialOnlyRedirect(host))
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
        _, data, _ = _read_url(robots_url, host=host, limit=MAX_ROBOTS_BYTES)
        robot.parse(data.decode("utf-8", errors="replace").splitlines())
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
        )
        if status != 200 or data.lstrip().startswith(b"%PDF"):
            raise ValueError("unsupported official source response")
        return data.decode("utf-8", errors="replace"), final_url

    return investigate_official_pages(
        url, now=now, fetch_html=fetch_page, robots_allowed=allowed,
        max_pages=3,
    )

def refresh(seeds: dict, public: dict, *, now: datetime, batch_size: int,
            recheck_no_explicit: bool = False, fetcher=check_official_url) -> dict:
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
    due = sorted(
        (i for i, item in enumerate(programmes)
         if i not in rechecking and eligible_for_check(item, now=now)),
        key=priority,
    )
    selected = set((needs_details + readable_negatives + due)[:batch_size])
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate offline; never fetch")
    parser.add_argument("--batch-size", type=int, default=25)
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
