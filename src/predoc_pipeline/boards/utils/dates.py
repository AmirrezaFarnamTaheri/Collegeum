"""Deadline / posting-date extraction from free text.

Deliberately regex-driven (no fuzzy parsing of whole paragraphs) so random numbers
in a job ad are never mistaken for a deadline.
"""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
    # a few non-English month names seen on Nordic / continental boards
    "januari": 1, "februari": 2, "mars": 3, "maj": 5, "juni": 6, "juli": 7,
    "augusti": 8, "oktober": 10, "janvier": 1, "février": 2, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12, "desember": 12, "januar": 1, "februar": 2, "märz": 3,
    "dezember": 12, "okt": 10, "des": 12, "dez": 12,
}
_MON = r"(?P<mon>" + "|".join(sorted((re.escape(m) for m in MONTHS), key=len, reverse=True)) + r")\.?"
_ORD = r"(?:st|nd|rd|th)?"

DATE_PATTERNS = [
    # 2026-10-31
    re.compile(r"\b(?P<y>20\d{2})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b"),
    # 31 October 2026 / 31st of Oct, 2026 / 1 Oct
    re.compile(r"\b(?P<d>\d{1,2})" + _ORD + r"\.?\s+(?:of\s+)?" + _MON + r",?\s*(?P<y>20\d{2})?\b", re.IGNORECASE),
    # October 31, 2026 / Oct 31st
    re.compile(r"\b" + _MON + r"\s+(?P<d>\d{1,2})" + _ORD + r",?\s*(?P<y>20\d{2})?\b", re.IGNORECASE),
    # 31-10-2026 / 31.10.2026 / 31/10/2026 (day-first; swapped if impossible)
    re.compile(r"\b(?P<d>\d{1,2})[./-](?P<m>\d{1,2})[./-](?P<y>20\d{2})\b"),
    # 5/24/26 - two-digit years are almost always US month-first
    re.compile(r"\b(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<yy>\d{2})\b"),
]

DEADLINE_LABELS = re.compile(
    r"(application\s+deadline|deadline(?:\s+for\s+applications?)?|closing\s+date|closes?(?:\s+on)?|"
    r"apply\s+(?:by|before|no\s+later\s+than)|applications?\s+(?:must\s+be\s+received|close|are\s+due)\s*(?:by|on)?|"
    r"applications?\s+(?:are\s+|will\s+be\s+)?(?:invited|accepted|welcome|open|received)\s+(?:until|through)|"
    r"submit(?:\s+your)?(?:\s+application)?\s+by|"
    r"last\s+(?:application\s+)?date|review\s+of\s+applications\s+(?:will\s+)?begins?(?:\s+on)?|"
    r"first\s+review(?:\s+date)?|ansök(?:an)?\s+senast|sista\s+ansökningsdag|søknadsfrist|ansøgningsfrist|"
    r"bewerbungsfrist|date\s+limite|fecha\s+l[ií]mite|scadenza)\s*[:\-–]?\s*",
    re.IGNORECASE,
)
ROLLING = re.compile(r"\b(rolling|until\s+filled)\b", re.IGNORECASE)
_DEADLINE_OR_REVIEW_RX = re.compile(r"deadline|review", re.IGNORECASE)
_POSTED_RECENT_RX = re.compile(r"\b\d+\s*(minute|hour)s?\s+ago")


def today() -> date:
    return datetime.now(UTC).date()


def _mk(y: int | None, m: int, d: int, ref: date) -> date | None:
    if m > 12 and d <= 12:
        m, d = d, m
    try:
        if y is None:
            cand = date(ref.year, m, d)
            # No year given: assume the next occurrence (allowing ~2 months back for
            # "closing date: 01 Oct" read shortly after it passed).
            if cand < ref - timedelta(days=60):
                cand = date(ref.year + 1, m, d)
            return cand
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str, ref: date | None = None) -> list[tuple[int, date]]:
    """Return (position, date) for every explicit date in text, sorted by position."""
    ref = ref or today()
    out: list[tuple[int, date]] = []
    taken: list[range] = []
    for pat in DATE_PATTERNS:
        for m in pat.finditer(text):
            if any(m.start() in r for r in taken):
                continue
            g = m.groupdict()
            month = int(g["m"]) if g.get("m") else MONTHS.get((g.get("mon") or "").lower().rstrip("."))
            if not month:
                continue
            year = int(g["y"]) if g.get("y") else (2000 + int(g["yy"])) if g.get("yy") else None
            d = _mk(year, month, int(g["d"]), ref)
            if d and 2000 < d.year < 2100:
                out.append((m.start(), d))
                taken.append(range(m.start(), m.end()))
    return sorted(out)


def parse_date(text: str | None, ref: date | None = None) -> date | None:
    if not text:
        return None
    found = find_dates(text, ref)
    return found[0][1] if found else None


def extract_deadline(text: str | None, ref: date | None = None) -> tuple[date | None, str | None]:
    """Find a deadline after a deadline-ish label. Returns (date, raw_snippet)."""
    if not text:
        return None, None
    matches = list(DEADLINE_LABELS.finditer(text))
    review_note = None
    rolling_note = None
    for index, m in enumerate(matches):
        end = min(m.end() + 90, matches[index + 1].start() if index + 1 < len(matches)
                  else len(text))
        window = text[m.end():end]
        # A different labelled date is not an application cutoff merely because
        # it falls inside the fixed lookahead window.
        other_date = re.search(
            r"\b(?:start(?:ing)?\s+(?:date|on)|expected\s+start|commencement|"
            r"interviews?(?:\s+(?:date|on))?|posted(?:\s+on)?|publication\s+date)\b",
            window, re.I)
        if other_date:
            window = window[:other_date.start()]
        snippet = (m.group(0) + window).strip()[:120]
        if re.search(r"review", m.group(0), re.I):
            review_note = review_note or snippet
            continue
        d = parse_date(window, ref)
        if d:
            return d, snippet
        if ROLLING.search(window[:40]):
            rolling_note = snippet
    if review_note:
        return None, review_note
    if rolling_note:
        return None, "Rolling"
    if ROLLING.search(text[:400]) and _DEADLINE_OR_REVIEW_RX.search(text[:400]):
        return None, "Rolling"
    return None, None


_REL = re.compile(r"(?P<n>\d+|a|an|one)\+?\s*(?P<unit>minute|hour|day|week|month)s?\s+ago", re.IGNORECASE)


def parse_posted(text: str | None, ref: date | None = None) -> date | None:
    """Parse 'Posted 3 Days Ago', 'Posted Today', '2 weeks ago', or an explicit date."""
    if not text:
        return None
    ref = ref or today()
    t = text.lower()
    if "today" in t or "just now" in t or _POSTED_RECENT_RX.search(t):
        return ref
    if "yesterday" in t:
        return ref - timedelta(days=1)
    m = _REL.search(t)
    if m:
        n = m.group("n")
        n = 1 if n in ("a", "an", "one") else int(n)
        mult = {"minute": 0, "hour": 0, "day": 1, "week": 7, "month": 30}[m.group("unit").lower()]
        return ref - timedelta(days=n * mult)
    return parse_date(text, ref)


def parse_iso_datetime(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return parse_date(value)
