"""Timezone-safe parsing and formatting of every timestamp we persist.

All timestamps are stored as ``YYYY-MM-DDTHH:MM:SSZ`` in UTC. That format sorts
lexicographically, round-trips through JSON unchanged, and compares correctly
against SQLite's ``strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)``. A mix of naive
and offset-bearing ISO strings does not: comparing ``2027-03-01T08:00:00+00:00``
against ``datetime('now')`` only appears to work because the date prefix
usually differs first.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

__all__ = [
    "TS_FORMAT", "utcnow", "to_utc", "parse_datetime", "format_ts",
    "days_between", "shift", "today_utc", "valid_iso_offset",
]

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_DATE_PATTERNS = (
    "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y",
    "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%Y/%m/%d",
)
_TIME_SPLIT = re.compile(r"[T ]\d{1,2}:\d{2}")
_YMD_REGEX = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

#: A label that introduces the date, as in "Deadline: 15 March 2027". A model
#: that echoes the advert's own wording returns the label with the date, and a
#: label is not part of the date -- but dropping the whole string loses a
#: perfectly good deadline. Only a *leading* label is stripped (the regex is
#: anchored), so a date that merely contains the word elsewhere is untouched.
_LABEL_PREFIX = re.compile(
    r"^(?:"
    r"application\s+deadline|deadline(?:\s+for\s+applications?)?|"
    r"closing\s+date|closing|closes?|"
    r"apply\s+by|apply\s+before|apply\s+no\s+later\s+than|"
    r"submit(?:\s+your)?(?:\s+application)?\s+by|"
    r"applications?\s+(?:close|are\s+due|are\s+invited\s+until|"
    r"must\s+be\s+received(?:\s+by)?)\s*(?:on|by)?|"
    r"last\s+(?:application\s+)?date|"
    r"bewerbungsfrist|sista\s+ans[öo]kningsdag|ans[öo]k(?:an)?\s+senast|"
    r"s[øo]knadsfrist|ans[øo]gningsfrist|"
    r"date\s+limite|fecha\s+l[ií]mite|scadenza"
    r")\s*[:\-–—]?\s*",
    re.IGNORECASE,
)


def valid_iso_offset(text: str) -> bool:
    """Reject overflowing offset components that fromisoformat normalizes."""
    if not _TIME_SPLIT.search(text):
        return True
    match = re.search(r"[+-](\d{2})(?::?(\d{2}))?(?::?(\d{2})(?:[.,]\d+)?)?$", text)
    if match is None:
        return True  # Other malformed syntax is rejected by the ISO parser.
    hour, minute, second = (int(part or 0) for part in match.groups())
    return hour < 24 and minute < 60 and second < 60


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_utc(value: datetime) -> datetime:
    """Attach UTC to naive datetimes, convert aware ones."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def format_ts(value: datetime | None = None) -> str:
    return to_utc(value or utcnow()).strftime(TS_FORMAT)


def parse_datetime(value: str | datetime | None) -> datetime | None:
    """Parse the date spellings that actually appear in academic adverts.

    Returns None rather than raising: an unparseable deadline means a listing
    with an unknown deadline, not a pipeline failure. Note that ``%m/%d/%Y`` is
    deliberately absent -- the corpus is non-US, so ``03/01/2027`` is 3 January,
    and guessing both ways silently produces two-month errors.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        try:
            return to_utc(value)
        except (ValueError, OverflowError):
            return None
    text = str(value).strip()
    # "Deadline: 15 March 2027" is a date with a label, not a date and a
    # label. Strip one leading label and parse what is left; everything after
    # it is still validated by the same rules, so trailing garbage stays
    # rejected.
    text = _LABEL_PREFIX.sub("", text, count=1).strip()
    if not text:
        return None
    if not valid_iso_offset(text):
        return None

    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return to_utc(datetime.fromisoformat(iso))
    except (ValueError, OverflowError):
        pass

    # An invalid ISO value is not evidence for a midnight deadline. Do not
    # silently discard its time, offset or trailing garbage via date fallback.
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return None

    head = _TIME_SPLIT.split(text)[0].strip().rstrip(",")
    for pattern in _DATE_PATTERNS:
        try:
            return to_utc(datetime.strptime(head, pattern))
        except ValueError:
            continue

    match = _YMD_REGEX.search(text)
    if match:
        try:
            year, month, day = (int(g) for g in match.groups())
            return to_utc(datetime(year, month, day))
        except ValueError:
            return None
    return None


def days_between(a: datetime | None, b: datetime | None) -> int | None:
    """Floor of the absolute elapsed-day gap, or None when either side is unknown.

    Both operands are normalised to UTC first: subtracting a naive datetime
    from an aware one raises TypeError, and that exception inside the
    deduplication loop takes down the run.
    """
    if a is None or b is None:
        return None
    return int(abs((to_utc(a) - to_utc(b)).total_seconds()) // 86400)


def shift(days: int, *, base: datetime | None = None) -> datetime:
    return to_utc(base or utcnow()) + timedelta(days=days)


def today_utc() -> date:
    return utcnow().date()
