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

# These are evidence of an incomplete cutoff, never candidate dates. Keep them
# separate so relative posting-date parsing retains its existing behaviour.
_INCOMPLETE_DEADLINE_PATTERNS = [
    re.compile(r"(?<![\w./-])\d{1,4}[./-]\d{1,2}(?:[./-]\d{1,4})?(?!\w|[./-]\d)"),
    re.compile(r"\b" + _MON + r"\s+20\d{2}\b", re.IGNORECASE),
]
_DEADLINE_DATE_PATTERNS = [*DATE_PATTERNS, *_INCOMPLETE_DEADLINE_PATTERNS]
_REVIEW_CONTEXT = re.compile(
    r"\b(?:priority|(?:first|initial)\s+review|review\s+date|full\s+consideration)\b",
    re.IGNORECASE,
)
_OTHER_FIELD_LABEL = re.compile(
    r"\b(?:requirements|qualifications|experience|(?:work(?:ing)?\s+)?schedule|"
    r"salary|compensation|contact|duties|responsibilities|benefits)\s*:", re.IGNORECASE,
)
_NONAPPLICATION_PREFIX = re.compile(
    r"\b(?:funding|scholarship|references?|recommendations?)\s*$", re.IGNORECASE,
)

DEADLINE_LABELS = re.compile(
    r"(priority\s+(?:application\s+)?deadline|priority\s+(?:application|review|consideration)\s+date|"
    r"application\s+deadline|deadline(?:\s+for\s+applications?)?|closing\s+date|closes?(?:\s+on)?|"
    r"apply\s+(?:by|before|no\s+later\s+than)|applications?\s+(?:must\s+be\s+received|close|are\s+due)\s*(?:by|on)?|"
    r"applications?\s+(?:are\s+|will\s+be\s+)?(?:invited|accepted|welcome|open|received)\s+(?:until|through)|"
    r"submit(?:\s+your)?(?:\s+application)?\s+by|"
    r"last\s+(?:application\s+)?date|review\s+of\s+applications\s+(?:will\s+)?begins?(?:\s+on)?|"
    r"first\s+review(?:\s+date)?|review\s+date|ansök(?:an)?\s+senast|sista\s+ansökningsdag|søknadsfrist|ansøgningsfrist|"
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


def parse_deadline_date(text: str | None) -> date | None:
    """Read a single fully qualified cutoff without guessing its year or order.

    Posting dates keep the permissive ``parse_date`` contract. A deadline needs
    its own four-digit year, a valid calendar date and unambiguous numeric order.
    Multiple different dates or an incomplete date in the same field do not
    establish one cutoff. Repeated representations of the same date are fine.
    """
    if not text:
        return None
    candidates: list[date | None] = []
    taken: list[tuple[int, int]] = []
    for pattern in _DEADLINE_DATE_PATTERNS:
        for match in pattern.finditer(text):
            if any(match.start() < end and match.end() > start for start, end in taken):
                continue
            # Claim invalid/incomplete spans too: a different pattern must not
            # salvage a substring of an invalid ISO date or borrow another year.
            taken.append(match.span())
            groups = match.groupdict()
            value = None
            # A date prefix inside a longer malformed token is not a complete
            # date (for example 2027-01-15/16 or 2027-01-15-2028).
            extended_token = (
                re.search(r"\d[./-]$", text[:match.start()])
                or re.match(r"[./-]\d", text[match.end():])
            )
            if groups.get("y") and not extended_token:
                year = int(groups["y"])
                day = int(groups["d"])
                month = (int(groups["m"]) if groups.get("m") else
                         MONTHS[(groups.get("mon") or "").lower().rstrip(".")])
                # ISO year-first order is fixed. Other all-numeric dates can be
                # day-first or month-first only when both yield the same answer
                # or exactly one is a valid ordering. Never repair invalid ISO.
                numeric = not groups.get("mon") and match.start("y") != match.start()
                ambiguous = numeric and day <= 12 and month <= 12 and day != month
                mixed_separators = numeric and len(set(re.findall(r"[./-]", match.group()))) != 1
                if numeric and month > 12 and day <= 12:
                    month, day = day, month
                if not ambiguous and not mixed_separators and 2000 < year < 2100:
                    try:
                        value = date(year, month, day)
                    except ValueError:
                        pass
            candidates.append(value)
    unique = set(candidates)
    return unique.pop() if len(unique) == 1 and None not in unique else None


def extract_deadline(text: str | None, ref: date | None = None) -> tuple[date | None, str | None]:
    """Find an explicit, unambiguous cutoff after its label, retaining raw evidence.

    ``ref`` remains accepted for caller compatibility; cutoff years never depend
    on the current or reference date. Relative posting dates are parsed separately.
    """
    if not text:
        return None, None
    matches = list(DEADLINE_LABELS.finditer(text))
    review_note = None
    rolling_note = None
    candidates: list[date | None] = []
    evidence: list[str] = []
    for index, m in enumerate(matches):
        # Inspect the whole field before deciding. A fixed lookahead can cut off
        # a later alternative or its priority qualifier after an otherwise valid
        # first date. Independently labelled sections still end this field.
        next_match = matches[index + 1] if index + 1 < len(matches) else None
        end = next_match.start() if next_match else len(text)
        window = text[m.end():end]
        # A parenthesized role after a date belongs to that date, even when its
        # words also match a standalone review label.
        if (next_match and _REVIEW_CONTEXT.search(next_match.group(0))
                and re.search(r"[\[(][^\])]*$", window)):
            close = re.search(r"[\])]", text[next_match.end():])
            end = next_match.end() + close.end() if close else next_match.end()
            window = text[m.end():end]
        # A different labelled section/date is not an application cutoff merely
        # because it follows the cutoff field in the page's text representation.
        other_date = re.search(
            r"\b(?:start(?:ing)?\s+(?:date|on)|expected\s+start|commencement|"
            r"interviews?(?:\s+(?:date|on))?|posted(?:\s+on)?|publication\s+date)\b",
            window, re.I)
        if other_date:
            window = window[:other_date.start()]
        other_field = _OTHER_FIELD_LABEL.search(window)
        if other_field:
            window = window[:other_field.start()]
        # Include a qualifier in the same preceding clause, while excluding a
        # previous labelled review field from an independently stated final date.
        previous_end = matches[index - 1].end() if index else 0
        prefix = re.split(r"[.;!?\n]", text[previous_end:m.start()])[-1]
        if (index and _REVIEW_CONTEXT.search(matches[index - 1].group(0))
                and re.fullmatch(r"[\s,/:()–—-]*", text[previous_end:m.start()])):
            # "First review, Deadline: DATE" is one qualified field, not an
            # empty review field followed by an independent final cutoff.
            prefix = text[matches[index - 1].start():m.start()]
        if _NONAPPLICATION_PREFIX.search(prefix):
            continue
        prefix_review = bool(_REVIEW_CONTEXT.search(prefix))
        snippet = ((prefix if prefix_review else "") + m.group(0) + window).strip()
        if (re.search(r"review|priority", m.group(0), re.I)
                or prefix_review or _REVIEW_CONTEXT.search(window)):
            if (review_note is None
                    or (not any(pattern.search(review_note) for pattern in _DEADLINE_DATE_PATTERNS)
                        and any(pattern.search(snippet) for pattern in _DEADLINE_DATE_PATTERNS))):
                review_note = snippet
            continue
        d = parse_deadline_date(window)
        if any(pattern.search(window) for pattern in _DEADLINE_DATE_PATTERNS):
            candidates.append(d)
            evidence.append(snippet)
        if ROLLING.search(window[:40]):
            rolling_note = snippet
    unique = set(candidates)
    if len(unique) == 1 and None not in unique:
        cutoff = unique.pop()
        # A short excerpt is useful only when it still contains the complete
        # accepted date. Rejected evidence below keeps its competing dates and
        # qualifiers, so a second pass cannot resurrect a truncated first date.
        short = evidence[0][:120]
        return cutoff, short if parse_deadline_date(short) == cutoff else evidence[0]
    if evidence:
        # Keep every competing field, including a partial/invalid field, so a
        # subsequent caller cannot mistake the first field for the full evidence.
        return None, "\n".join(dict.fromkeys(evidence))
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
