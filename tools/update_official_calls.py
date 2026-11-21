"""Bounded, robots-aware discovery of independent official Economics PhD calls.

Independent of LinkedIn feed posts, third-party deadlines and the 251-programme
admissions directory. No Telegram credentials, vacancy ingestion or remote sends.
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
    from .official_robots import parse_official_robots
else:
    from official_robots import parse_official_robots
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "config/official_phd_calls_sources.json"
CATALOG = ROOT / "docs/data/official_phd_calls.json"
USER_AGENT = "CollegeumOfficialCalls/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
MAX_HTML_BYTES = 1024 * 1024
MAX_ROBOTS_BYTES = 256 * 1024
MAX_INDEX_LINKS = 6
# Generic index anchors are candidates only when context AND path match.
_GENERIC_DETAIL_LABEL = re.compile(
    r"^(?:web personal|read more|learn more|view details|more information|"
    r"ver m[aá]s|veure m[eé]s)$", re.I,
)
_PHD_CALL_PATH = re.compile(
    r"phd|ph-d|doctorat|doctoral|scholarship|fellowship|studentship|bursar", re.I,
)
MAX_SOURCES = 20
MAX_CALLS = 100
MAX_CHECK_AGE = timedelta(days=14)
STATUSES = {"verified", "no_explicit_deadline", "ambiguous_deadline", "unrelated",
            "closed",
            "robots_unavailable", "robots_disallowed", "fetch_failed", "unsafe_redirect",
            "not_seen"}
DATE_RE = re.compile(
    r"\b(?P<iso>20\d{2}-\d{2}-\d{2})\b|"
    r"\b(?P<d1>\d{1,2})(?:st|nd|rd|th)?\s+(?P<m1>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
    r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s*,?\s*(?P<y1>20\d{2})\b|"
    r"\b(?P<m2>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
    r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+(?P<d2>\d{1,2})(?:st|nd|rd|th)?"
    r"\s*,?\s*(?P<y2>20\d{2})\b",
    re.I,
)
CALL_TITLE = re.compile(r"\bph\.?\s*d\.?\b.*\b(?:scholarships?|fellowships?|studentships?)\b|"
                        r"\b(?:scholarships?|fellowships?|studentships?|bursar(?:y|ies))\b.*\bph\.?\s*d\.?\b|"
                        r"\bph\.?\s*d\.?\b.*\bbursar(?:y|ies)\b", re.I)
EXCLUDE = re.compile(r"\b(?:post[-\s]?doc(?:toral)?|assistant professor|"
                     r"visiting professor|workshop|seminar|conference)\b", re.I)
SUBJECT = re.compile(r"\b(?:economics?|finance|account(?:ing|ancy)|"
                     r"business|econometrics?|climate|energy|"
                     r"quantitative|strategy|informatics|operations)\b", re.I)
_RESTRICTED_PATH = re.compile(
    r"(?:\.(?:pdf|docx?|xlsx?|zip|png|jpe?g)$|"
    r"/(?:login|log-in|signup|register|api|wp-admin|job-market|events?)(?:/|$))", re.I,
)


class CallHTML(HTMLParser):
    """Tiny stdlib HTML-to-text/anchor parser; never runs page scripts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        # Keep the article beginning at its first H1 distinct from site navigation.
        self.content_chunks: list[str] = []
        self._content_started = False
        self.headings: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.document_links: list[tuple[str, str, str]] = []
        self._latest_section = ""
        self._section_parts: list[str] | None = None
        self._ignored = 0
        self._heading: list[str] | None = None
        self._link: list[str] | None = None
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self._ignored += 1
            return
        if self._ignored:
            return
        if tag == "h1":
            self._content_started = True
            self._heading = []
        elif tag in {"h2", "h3", "h4"}:
            self._section_parts = []
        if tag in {"p", "li", "div", "h1", "h2", "h3", "footer", "br", "tr"}:
            self.chunks.append(" ")
            if self._content_started:
                self.content_chunks.append(" ")
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._link = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "template"}:
            self._ignored = max(0, self._ignored - 1)
            return
        if self._ignored:
            return
        if tag == "h1" and self._heading is not None:
            heading = " ".join(" ".join(self._heading).split())
            if heading:
                self.headings.append(heading)
            self._heading = None
        if tag in {"h2", "h3", "h4"} and self._section_parts is not None:
            self._latest_section = " ".join(" ".join(self._section_parts).split())
            self._section_parts = None
        if tag == "a":
            label = " ".join(" ".join(self._link or []).split())
            if self._href and label:
                self.links.append((self._href, label))
                self.document_links.append((self._href, label, self._latest_section))
            self._link, self._href = None, None
        if tag in {"p", "li", "div", "h1", "h2", "h3", "footer", "tr"}:
            self.chunks.append(" ")
            if self._content_started:
                self.content_chunks.append(" ")

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        self.chunks.append(data)
        if self._content_started:
            self.content_chunks.append(data)
        if self._heading is not None:
            self._heading.append(data)
        if self._section_parts is not None:
            self._section_parts.append(data)
        if self._link is not None:
            self._link.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self.chunks).split())

    def content_text(self) -> str:
        return " ".join(" ".join(self.content_chunks).split())


def safe_official_url(raw: str, root: str) -> str | None:
    """HTTPS exact-host links only, without tracking queries, credentials or files."""
    try:
        base = urllib.parse.urlsplit(root)
        parsed = urllib.parse.urlsplit(urllib.parse.urljoin(root, raw))
        host = (parsed.hostname or "").lower().removeprefix("www.")
        expected = (base.hostname or "").lower().removeprefix("www.")
        port, base_port = parsed.port, base.port
    except (ValueError, TypeError):
        return None
    if (parsed.scheme != "https" or base.scheme != "https" or host != expected
            or not host or port not in (None, 443) or base_port not in (None, 443)
            or parsed.username or parsed.password or base.username or base.password
            or _RESTRICTED_PATH.search(parsed.path)
            or not parsed.path.startswith("/") or len(parsed.path) > 350):
        return None
    # Avoid query-driven search requests, tracking aliases and duplicate variants.
    if parsed.query:
        return None
    return urllib.parse.urlunsplit(("https", parsed.netloc, parsed.path, "", ""))


def _date(match: re.Match[str]) -> date | None:
    try:
        if match.group("iso"):
            return date.fromisoformat(match.group("iso"))
        month = (match.group("m1") or match.group("m2")).lower()[:3]
        m = ("jan", "feb", "mar", "apr", "may", "jun", "jul",
             "aug", "sep", "oct", "nov", "dec").index(month) + 1
        return date(int(match.group("y1") or match.group("y2")), m,
                    int(match.group("d1") or match.group("d2")))
    except (TypeError, ValueError):
        return None


def _stamp(now: datetime) -> str:
    return now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _location_proof(text: str, country: str, url: str) -> str | None:
    host = (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")
    suffix = "uk" if country in {"UK", "GB"} else country.lower()
    if host.endswith("." + suffix):
        return f"{country}: official national institutional domain {host}"
    # The generic .edu domain needs independent contact evidence, not the
    # institution name or an upstream discovery-list country assumption.
    if country == "ES" and re.search(
        r"(?:C/\s*John\s+M\.\s*Keynes.{0,55}08034\s+Barcelona|"
        r"08034\s+Barcelona.{0,80}(?:Tel\.?\s*)?\+\s*34)", text, re.I,
    ) and re.search(r"(?:Tel\.?\s*)?\+\s*34\s*\d{2}", text, re.I):
        return "ES: official postal address 08034 Barcelona and telephone +34"
    return None


def _intake(title: str, text: str) -> int | None:
    """Prefer the explicitly OPEN cycle, never a nearby CLOSED preceding cycle.

    Academic funding pages often show 2026/27 now closed followed by 2027/28
    now open. A loose lookahead from 2026/27 can cross into 2027/28 and produce
    a valid-looking, but wrong, deduplication key.
    """
    periods = list(re.finditer(
        r"(?:studentship|scholarship)\s+applications?\s+for\s+the\s+"
        r"(20\d{2})/\d{2}\s+academic\s+year\b",
        text, re.I,
    ))
    open_years: set[int] = set()
    for index, match in enumerate(periods):
        boundary = periods[index + 1].start() if index + 1 < len(periods) else len(text)
        tail = text[match.end():min(boundary, match.end() + 120)]
        # The availability marker must belong to THIS application cycle.
        # A closed or conflicting notice cannot be promoted by a later one.
        if re.search(r"\b(?:now\s+closed|currently\s+closed|applications\s+closed)\b",
                     tail, re.I):
            continue
        if re.search(r"\b(?:now\s+open|currently\s+open|applications\s+are\s+open)\b",
                     tail, re.I):
            open_years.add(int(match.group(1)))
    if len(open_years) > 1:
        return None  # Ambiguous simultaneous cycles: manual institutional review.
    title_year = re.search(r"\b(20\d{2})\b", title)
    if open_years:
        year = next(iter(open_years))
        if title_year and int(title_year.group(1)) != year:
            return None  # Contradictory explicit evidence.
        return year
    if title_year:
        return int(title_year.group(1))
    match = re.search(
        r"(?:starting|start(?:s|ing)?)\s+(?:in\s+)?"
        r"(?:September|October|Autumn)"
        r"(?:\s*(?:/|or)\s*(?:September|October))?\s+(20\d{2})", text, re.I,
    )
    if not match:
        match = re.search(
            r"commence.{0,95}?(?:in\s+)?(?:September|October|Autumn)\s+(20\d{2})",
            text, re.I,
        )
    return int(match.group(1)) if match else None



_FUNDING_CYCLE = re.compile(
    r"(?:studentship|scholarship)\s+applications?\s+for\s+the\s+"
    r"(20\d{2})/\d{2}\s+academic\s+year\b",
    re.I,
)
_CLOSED_NOTICE = re.compile(
    r"\b(?:now|currently)\s+closed\b|\bapplications?\s+(?:are|have)\s+closed\b",
    re.I,
)
_GENERIC_FUNDING_CLOSED = re.compile(
    r"\b(?:scholarships?|studentships?|fellowships?|bursar(?:y|ies))\b"
    r".{0,95}?\b(?:now|currently)\s+closed\b",
    re.I,
)


def _funding_closed(text: str, intake_year: int | None) -> bool:
    """Reject a closed call without confusing last year's closed cycle.

    University pages often preserve a previous academic year's closure notice.
    A current open cycle takes precedence over unrelated older closures, but
    any explicit closure of the identified current cycle fails closed.
    """
    periods = list(_FUNDING_CYCLE.finditer(text))
    unmasked: list[str] = []
    position = 0
    for index, period in enumerate(periods):
        boundary = periods[index + 1].start() if index + 1 < len(periods) else len(text)
        notice = _CLOSED_NOTICE.search(
            text, period.end(), min(boundary, period.end() + 120),
        )
        if intake_year is not None and int(period.group(1)) == intake_year:
            if notice:
                return True  # The current cycle explicitly closed.
            continue
        if notice:
            # Remove only the *old year's* closed notice. Preserve later
            # generic current-cycle closure text from the same document.
            end = notice.end()
            unmasked.append(text[position:period.start()])
            unmasked.append(" " * (end - period.start()))
            position = end
    unmasked.append(text[position:])
    return _GENERIC_FUNDING_CLOSED.search("".join(unmasked)) is not None

def _date_candidates(text: str, *, kind: str, now: datetime) -> list[tuple[date, str, str]]:
    candidates: list[tuple[date, str, str]] = []
    for match in DATE_RE.finditer(text):
        day = _date(match)
        if day is None or not now.date() <= day <= date(now.year + 2, 12, 31):
            continue
        before = text[max(0, match.start() - 190):match.start()]
        after = text[match.end():match.end() + 38]
        # These are application-funding cutoffs, never generic PhD admissions,
        # orientation dates, recommendations or grant decision announcements.
        funding = bool(re.search(
            r"(?:scholarship|studentship|fellowship)\s+applications?.{0,125}"
            r"(?:deadline|close(?:s|d)?\s+on|due(?:\s+to)?|by)\s*$",
            before, re.I,
        ))
        if not funding:
            funding = bool(re.search(
                r"(?:studentship|scholarship)\s+applications?.{0,125}"
                r"(?:will\s+close\s+on)\s*$", before, re.I,
            ))
        if not funding and kind in {"phd_studentship", "phd_bursary"}:
            # On a PhD-studentship-specific official page, a clearly marked
            # funding Deadline section may say "deadline for applications"
            # instead of repeating "studentship". Never generalize this to
            # a university-wide PhD admissions page.
            funding = bool(re.search(
                r"\bDeadline\s+(?:(?:The\s+)?deadline\s+for\s+applications\s+is|for\s+applications\s+(?:The\s+)?deadline\s+by\s+which\s+to\s+apply\s+is)\s+"
                r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+)?$",
                before, re.I,
            ))
        submission = kind in {"phd_scholarship", "phd_fellowship"} and bool(re.search(
            r"interested\s+candidates\s+must\s+complete\s+both.{0,100}"
            r"(?:steps\s+)?(?:by|before)\s*$", before, re.I,
        ))
        if not (funding or submission):
            continue
        # An "or" alternative may be a second distinct legal cutoff.
        candidate_excerpt = " ".join(
            (text[max(0, match.start() - 120):match.end() + 40]).split()
        )
        candidates.append((day, "funding" if funding else "scholarship",
                           candidate_excerpt[:230]))
        if re.match(r"\s+or\s+", after, re.I):
            return [(day, "ambiguous", candidate_excerpt)]
    return candidates


def extract_call(
    html: str, *, url: str, source: dict[str, Any], now: datetime,
) -> dict[str, Any]:
    """Pure extraction. Missing or conflicting official evidence fails closed."""
    if now.tzinfo is None:
        raise ValueError("Expected timezone-aware clock")
    parsed = CallHTML()
    parsed.feed(html[:MAX_HTML_BYTES])
    text = parsed.text()
    # Long institutional menus can exceed 450 characters; only the primary
    # funding call's article, not navigation/footer, establishes subject fit.
    article = parsed.content_text() or text
    # University CMS superscripts can render ordinal dates as "30 th April".
    article = re.sub(r"(\d{1,2})\s+(st|nd|rd|th)\b", r"\1\2", article, flags=re.I)
    title = (parsed.headings[0] if parsed.headings else source.get("title", "")).strip()
    label = f"{title} {source.get('title', '')}"
    invalid = (not title or len(title) > 150
               or not (SUBJECT.search(label + " " + article[:1800])
                       or (source.get("subject_scope") == "multidisciplinary"
                           and source.get("mode") == "detail"
                           and "bursar" in label.lower()))
               or EXCLUDE.search(title)
               or not safe_official_url(url, source["url"]))
    # Mentioning scholarship terms somewhere in a generic admissions page
    # does not create an independent current funding call.
    relevant = CALL_TITLE.search(label) is not None
    status = "unrelated" if invalid or not relevant else "no_explicit_deadline"
    kind = ("phd_bursary" if re.search(r"\bbursar(?:y|ies)\b", label, re.I)
            else "phd_studentship" if "studentship" in (label + " " + article[:500]).lower()
            else "phd_fellowship" if "fellowship" in label.lower()
            else "phd_scholarship")
    intake_year = _intake(title, article)
    date_iso = None
    deadline_kind = None
    excerpt = None
    if status != "unrelated" and _funding_closed(article, intake_year):
        status = "closed"
    if status not in {"unrelated", "closed"}:
        values = _date_candidates(article, kind=kind, now=now)
        dates = {item[0] for item in values}
        if any(item[1] == "ambiguous" for item in values) or len(dates) > 1:
            status = "ambiguous_deadline"
        elif len(dates) == 1 and intake_year is not None:
            chosen = values[0]
            date_iso, deadline_kind, excerpt = (chosen[0].isoformat(), chosen[1], chosen[2])
            status = "verified"
    recommended = None
    if kind == "phd_studentship":
        rec = re.search(r"(?:strongly\s+advise|recommend)\s+submitting\s+your\s+"
                        r"application\s+no\s+later\s+than\s+", article, re.I)
        if rec:
            match = DATE_RE.search(article, rec.end())
            if match and match.start() - rec.end() <= 6:
                day = _date(match)
                if day and now.date() <= day <= date(now.year + 2, 12, 31):
                    recommended = day.isoformat()
    home_eligibility = (
        re.search(
            r"\b(?:bursaries?|scholarships?)\s+are\s+open\s+to\s+"
            r"Home\s+students?\s+only\b", article, re.I,
        ) if kind == "phd_bursary" else None
    )
    home_tuition = (
        re.search(r"\b(?:PhD\s+)?tuition\s+fees?\s+at\s+the\s+Home\s+rate\b",
                  article, re.I)
        if kind == "phd_bursary" else None
    )
    proof = _location_proof(text, str(source["country_code"]), url)
    # A broad, multi-disciplinary funding scheme is eligible, but must never
    # be advertised as Economics-only merely because one eligible school is
    # Henley. Only an Economics-specific call title earns the Economics label.
    scope = (
        "multidisciplinary" if source.get("subject_scope") == "multidisciplinary"
        else "economics" if re.search(r"\b(?:economics?|econometrics?)\b", title, re.I)
        else "finance" if re.search(r"\b(?:finance|accounting|accountancy)\b", title, re.I)
        else "multidisciplinary"
    )
    return {
        "source_id": source["id"],
        "posting_group": source.get("posting_group"),
        "posting_group_expected": source.get("posting_group_expected"),
        "eligibility_scope": "home_only" if home_eligibility else None,
        "eligibility_evidence_excerpt": (
            home_eligibility.group(0) if home_eligibility else None
        ),
        "funding_scope": "home_rate_tuition" if home_tuition else None,
        "funding_evidence_excerpt": home_tuition.group(0) if home_tuition else None,
        "institution": source["institution"],
        "country_code": source["country_code"],
        "official_url": url,
        "title": title if status != "unrelated" else source.get("title", title)[:150],
        "status": status,
        "kind": kind,
        "subject_scope": scope,
        "intake_year": intake_year,
        "deadline_iso": date_iso,
        "deadline_kind": deadline_kind,
        "recommended_admission_iso": recommended,
        "evidence_url": url if date_iso else None,
        "evidence_excerpt": excerpt,
        "location_evidence": proof,
        "location_evidence_url": url if proof else None,
        "checked_at": _stamp(now),
    }


def discover_links(html: str, source: dict[str, Any]) -> list[str]:
    """Bounded same-host index discovery; prioritize calls with subject evidence.

    Official indexes sometimes label legitimate awards "PhD Scholarship 2027"
    without repeating Economics or Finance in the anchor text. Follow those
    HTML calls after the obviously relevant ones; the independently fetched
    article must STILL prove subject fit before verification.
    """
    parser = CallHTML()
    parser.feed(html[:MAX_HTML_BYTES])
    root = source["url"]
    topical: list[str] = []
    generic: list[str] = []
    seen: set[str] = set()
    for href, label, heading in parser.document_links[:500]:
        label_is_call = bool(CALL_TITLE.search(label) and not EXCLUDE.search(label))
        heading_is_call = bool(CALL_TITLE.search(heading) and not EXCLUDE.search(heading))
        candidate = safe_official_url(href, root)
        if candidate is None or candidate == root or candidate in seen:
            continue
        if not label_is_call and not (
            heading_is_call and _GENERIC_DETAIL_LABEL.fullmatch(label.strip())
            and _PHD_CALL_PATH.search(urllib.parse.urlsplit(candidate).path)
        ):
            continue
        seen.add(candidate)
        (topical if SUBJECT.search(f"{heading} {label}") else generic).append(candidate)
    return (topical + generic)[:MAX_INDEX_LINKS]


def discover_document_links(html: str, source: dict[str, Any]) -> list[str]:
    """Bounded, same-host institutional PDF/DOC links with nearby heading context.

    University call indexes often make every PDF anchor say "Download PDF";
    the adjacent h2/h3/h4 names the PhD scholarship. This only discovers
    candidates for a separate opt-in reviewer, NEVER verified funding calls.
    """
    parser = CallHTML()
    parser.feed(html[:MAX_HTML_BYTES])
    root = urllib.parse.urlsplit(source["url"])
    host = (root.hostname or "").lower().removeprefix("www.")
    seen: set[str] = set()
    urls: list[str] = []
    for href, label, heading in parser.document_links[:500]:
        context = f"{heading} {label}"
        if not CALL_TITLE.search(context) or EXCLUDE.search(context):
            continue
        try:
            candidate = urllib.parse.urlsplit(
                urllib.parse.urljoin(source["url"], href),
            )
            candidate_host = (candidate.hostname or "").lower().removeprefix("www.")
            if (candidate.scheme != "https" or candidate_host != host
                    or candidate.port not in (None, 443)
                    or candidate.username or candidate.password
                    or candidate.query or candidate.fragment
                    or not re.search(r"\.(?:pdf|docx?)$", candidate.path, re.I)):
                continue
        except (TypeError, ValueError):
            continue
        url = urllib.parse.urlunsplit((
            candidate.scheme, candidate.netloc, candidate.path, "", "",
        ))
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def unsupported_document_count(html: str, source: dict[str, Any]) -> int:
    """Unverified, same-host funding-document coverage gaps only."""
    return len(discover_document_links(html, source))


def validate_sources(config: Any) -> None:
    if (not isinstance(config, dict)
            or config.get("kind") != "official_phd_call_sources"
            or config.get("version") != 1
            or not isinstance(config.get("sources"), list)
            or not 1 <= len(config["sources"]) <= MAX_SOURCES):
        raise ValueError("Invalid approved official-call source registry")
    ids: set[str] = set()
    urls: set[str] = set()
    group_members: dict[str, list[dict[str, Any]]] = {}
    for source in config["sources"]:
        if not isinstance(source, dict):
            raise ValueError("Invalid call source")
        name = source.get("id")
        url = source.get("url")
        if (not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,45}", name)
                or name in ids or not isinstance(url, str)
                or safe_official_url(url, url) != url
                or source.get("mode") not in {"index", "detail"}
                or (source.get("posting_group") is not None and (
                    not isinstance(source["posting_group"], str) or
                    not re.fullmatch(r"[a-z][a-z0-9-]{2,47}", source["posting_group"])))
                or (source.get("posting_group_expected") is not None and (
                    type(source["posting_group_expected"]) is not int
                    or not 2 <= source["posting_group_expected"] <= 6))
                or (source.get("posting_group") is None
                    and source.get("posting_group_expected") is not None)
                or not isinstance(source.get("institution"), str)
                or not 5 <= len(source["institution"]) <= 120
                or source.get("country_code") not in {"ES", "UK", "GB", "DE", "FI",
                                                      "FR", "NL", "IT", "SE", "NO",
                                                      "DK", "CH", "AT", "BE"}):
            raise ValueError("Unapproved or malformed official-call source")
        if url in urls:
            raise ValueError("Duplicate official-call URL in source registry")
        # Opt-in PDF/DOCX approvals are review only. No document is
        # fetched by the stdlib-only daily HTML monitor, and no review result
        # is inserted into the Telegram publishing catalogue.
        approved = source.get("approved_documents", [])
        if (not isinstance(approved, list) or len(approved) > 6
                or (approved and source["mode"] != "index")):
            raise ValueError("Invalid reviewed document source list")
        document_urls: set[str] = set()
        for document in approved:
            if not isinstance(document, dict):
                raise ValueError("Malformed approved document record")
            target = document.get("url")
            title = document.get("title")
            marker = document.get("institution_marker")
            canonical = document.get("canonical_html_url")
            try:
                parsed = urllib.parse.urlsplit(target)
                parent = urllib.parse.urlsplit(url)
                same_host = (
                    (parsed.hostname or "").lower().removeprefix("www.")
                    == (parent.hostname or "").lower().removeprefix("www.")
                )
                port = parsed.port
            except (TypeError, ValueError):
                raise ValueError("Invalid approved document URL") from None
            if (not isinstance(target, str) or target in document_urls
                    or not same_host or parsed.scheme != "https"
                    or port not in (None, 443) or parsed.username or parsed.password
                    or parsed.query or parsed.fragment or "%" in parsed.path
                    or not re.search(r"\.(?:pdf|docx)\Z", parsed.path, re.I)
                    or not isinstance(title, str) or not CALL_TITLE.search(title)
                    or EXCLUDE.search(title) or len(title) > 150
                    or not isinstance(marker, str) or not 8 <= len(marker) <= 100
                    or not isinstance(canonical, str)
                    or safe_official_url(canonical, url) != canonical):
                raise ValueError("Unreviewed or conflicting institutional document")
            document_urls.add(target)
        ids.add(name)
        urls.add(url)
        if source.get("posting_group") is not None:
            if source.get("mode") != "detail" or not source.get("posting_group_expected"):
                raise ValueError("Reviewed posting groups require an explicit member count")
            group_members.setdefault(source["posting_group"], []).append(source)
    for group, members in group_members.items():
        expected = members[0]["posting_group_expected"]
        if (len(members) != expected
                or len({(item["institution"], item["country_code"])
                        for item in members}) != 1
                or any(item["posting_group_expected"] != expected for item in members)):
            raise ValueError(f"Invalid or incomplete approved posting group {group}")


def validate_catalog(catalog: Any) -> None:
    if (not isinstance(catalog, dict)
            or catalog.get("kind") != "official_phd_call_observations"
            or catalog.get("version") != 1
            or not isinstance(catalog.get("calls"), list)
            or not isinstance(catalog.get("sources"), list)
            or len(catalog["calls"]) > MAX_CALLS):
        raise ValueError("Invalid official-call catalogue")


def refresh_sources(
    config: dict[str, Any], previous: dict[str, Any], *,
    now: datetime, fetcher: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    validate_sources(config)
    # An empty fixture may supply calls without source summaries.
    if previous.get("calls") and previous.get("sources") is None:
        previous = {**previous, "sources": []}
    if previous.get("sources") is None:
        previous = {**previous, "sources": []}
    validate_catalog(previous)
    calls: dict[str, dict[str, Any]] = {}
    prior = previous.get("calls", [])
    if len(prior) > MAX_CALLS:
        raise ValueError("Unbounded prior call catalogue")
    for row in prior:
        if not isinstance(row, dict):
            raise ValueError("Invalid prior call")
        url = row.get("official_url")
        if isinstance(url, str):
            calls[url] = {**row, "status": "not_seen", "deadline_iso": None}
    summaries = []
    for source in config["sources"]:
        response = fetcher(source["url"])
        status = response.get("status") if isinstance(response, dict) else "fetch_failed"
        urls: list[str] = []
        failures = 0
        discovered_links = 0
        rechecked_links = 0
        new_html_links = 0
        unsupported_documents = 0
        document_candidates: list[str] = []
        document_formats = {"pdf": 0, "doc": 0, "docx": 0}
        blocked_details = 0
        if status == "ok" and isinstance(response.get("html"), str):
            if source["mode"] == "index":
                urls = discover_links(response["html"], source)
                discovered_links = len(urls)
                previously_seen = {row.get("official_url") for row in prior
                                   if isinstance(row, dict)}
                new_html_links = sum(url not in previously_seen for url in urls)
                document_candidates = discover_document_links(response["html"], source)
                unsupported_documents = len(document_candidates)
                for document_url in document_candidates:
                    kind = document_url.rsplit(".", 1)[-1].lower()
                    document_formats[kind] += 1
                # Older but still-open official calls can scroll off a paginated
                # university index. Recheck at most two within the same source
                # and deadline window, without trusting cached dates for sending.
                historical = sorted(
                    (
                        row for row in prior
                        if row.get("source_id") == source["id"]
                        and row.get("status") == "verified"
                        and isinstance(row.get("deadline_iso"), str)
                        and row["deadline_iso"] >= now.date().isoformat()
                        and isinstance(row.get("official_url"), str)
                        and safe_official_url(row["official_url"], source["url"])
                            == row["official_url"]
                        and row["official_url"] not in urls
                    ),
                    key=lambda item: (item["deadline_iso"], item["official_url"]),
                )[:2]
                rechecked_links = len(historical)
                urls.extend(row["official_url"] for row in historical)
            else:
                urls = [source["url"]]
        elif status not in STATUSES:
            status = "fetch_failed"
        for url in urls:
            detail = response if url == source["url"] else fetcher(url)
            if not isinstance(detail, dict) or detail.get("status") != "ok":
                failures += 1
                if isinstance(detail, dict) and detail.get("status") in {
                    "robots_disallowed", "robots_unavailable",
                }:
                    blocked_details += 1
                calls[url] = {
                    "source_id": source["id"], "institution": source["institution"],
                    "country_code": source["country_code"], "official_url": url,
                    "status": str(detail.get("status", "fetch_failed"))
                    if isinstance(detail, dict) else "fetch_failed",
                    "checked_at": _stamp(now), "deadline_iso": None,
                }
                continue
            final_url = detail.get("final_url", url)
            if (not isinstance(final_url, str)
                    or safe_official_url(final_url, source["url"]) != final_url):
                failures += 1
                continue
            html = detail.get("html")
            if not isinstance(html, str) or len(html.encode("utf-8")) > MAX_HTML_BYTES:
                failures += 1
                continue
            row = extract_call(html, url=final_url, source=source, now=now)
            calls[final_url] = row
        summaries.append({
            "id": source["id"], "institution": source["institution"],
            "index_url": source["url"], "status": (
                "partial" if failures else status
            ),
            "failed_details": failures, "blocked_details": blocked_details,
            "candidate_count": len(urls), "discovered_links": discovered_links,
            "new_html_links": new_html_links, "rechecked_links": rechecked_links,
            "document_candidates": document_candidates,
            "document_links_by_format": document_formats,
            "mode": source["mode"],
            "index_empty": bool(source["mode"] == "index"
                                and status == "ok" and discovered_links == 0),
            "unsupported_documents": unsupported_documents,
            "checked_at": _stamp(now),
        })
    return {
        "kind": "official_phd_call_observations", "version": 1,
        "generated_at": _stamp(now), "sources": summaries,
        "calls": sorted(calls.values(), key=lambda row: row.get("official_url", "")),
    }


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, host: str, allowed: Callable[[str], bool]) -> None:
        self.host = host
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            parsed = urllib.parse.urlsplit(newurl)
        except ValueError:
            raise ValueError("unsafe_redirect") from None
        if (parsed.scheme != "https"
                or (parsed.hostname or "").lower() != self.host
                or not self.allowed(newurl)):
            raise ValueError("unsafe_redirect") from None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_official(url: str) -> dict[str, Any]:
    """One robots check per host, fail-closed for blocked or unavailable sites."""
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname
        if parsed.scheme != "https" or not host or safe_official_url(url, url) != url:
            return {"status": "unsafe_redirect"}
        robot = urllib.robotparser.RobotFileParser()
        robot.set_url(f"https://{host}/robots.txt")
        opener = urllib.request.build_opener(
            SafeRedirect(host, lambda candidate: robot.can_fetch(USER_AGENT, candidate))
        )
        def read(address: str, limit: int) -> tuple[bytes, str]:
            req = urllib.request.Request(address, headers={
                "User-Agent": USER_AGENT, "Accept": "text/html",
            })
            with opener.open(req, timeout=9) as reply:
                data = reply.read(limit + 1)
                if len(data) > limit:
                    raise ValueError("response_too_large")
                return data, reply.geturl()
        try:
            robots_url = f"https://{host}/robots.txt"
            robots, final_robots_url = read(robots_url, MAX_ROBOTS_BYTES)
            if final_robots_url != robots_url:
                raise ValueError("unsafe_robots_redirect")
            parse_official_robots(robots, robot)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                robot.allow_all = True
            else:
                return {"status": "robots_unavailable"}
        except (OSError, TimeoutError, UnicodeError, ValueError):
            return {"status": "robots_unavailable"}
        if not robot.can_fetch(USER_AGENT, url):
            return {"status": "robots_disallowed"}
        body, final = read(url, MAX_HTML_BYTES)
        if safe_official_url(final, url) != final or body.lstrip().startswith(b"%PDF"):
            return {"status": "unsafe_redirect"}
        if not body.lstrip().lower().startswith((b"<", b"<!doctype")):
            return {"status": "fetch_failed"}
        return {"status": "ok", "html": body.decode("utf-8", errors="replace"),
                "final_url": final}
    except (OSError, TimeoutError, UnicodeError, ValueError, urllib.error.HTTPError):
        return {"status": "fetch_failed"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Offline validation only")
    args = parser.parse_args(argv)
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))
    old = json.loads(CATALOG.read_text(encoding="utf-8"))
    validate_sources(sources)
    validate_catalog(old)
    if args.check:
        print("Official calls: registry and catalogue valid; network not used")
        return 0
    new = refresh_sources(sources, old, now=datetime.now(UTC), fetcher=fetch_official)
    CATALOG.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
    counts: dict[str, int] = {}
    for row in new["calls"]:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print("Official PhD call discovery:", json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
