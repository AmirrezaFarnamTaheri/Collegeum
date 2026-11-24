"""Interpret reviewed Asian Economics doctoral admissions timetables.

No stored date overrides or network access. Exact source routes, programme
identity and complete application-submission roles are required together.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlsplit

_YEARLESS_OPEN = re.compile(
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?"
    r"(?:\s*\((?:\d{1,2}(?::\d{2})?\s*(?:am|pm)/)?"
    r"(?:Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|Thu(?:rs(?:day)?)?|"
    r"Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)\))?",
    re.I,
)


def collect_deadline(parser, *, now, source_url, date_pattern, parse_date):
    """Return None for an unhandled route; handled sources fail closed."""
    source = urlsplit(source_url or "")
    host = (source.hostname or "").lower().removeprefix("www.")
    if (host, source.path.rstrip("/")) != (
        "econ.kyoto-u.ac.jp", "/kueac/application/doctoral",
    ):
        return None
    empty = ("no_explicit_deadline", None, None)
    if source.scheme != "https" or source.username or source.password:
        return empty
    text = parser.text()
    if not (
        "Application Procedures for Doctoral Programme" in parser.headings
        and "International Graduate Programme for East Asia Sustainable "
        "Economic Development Studies" in text
        and re.search(r"Graduate School of Economics", text, re.I)
        and any(re.fullmatch(
            r"Overall Schedule for Application and Selection\s*"
            r"\(Date and Time\s*:\s*JST\)", value,
        ) for tag, value in parser.tagged_blocks if tag in {"h2", "h3", "h4"})
    ):
        return empty

    # Official page reviewed 2026-11-24:
    # https://www.econ.kyoto-u.ac.jp/kueac/application/doctoral/
    # The dated range and its role share a table row. "Application Documents"
    # here denotes the complete formal application, paired with the exam fee;
    # separate AAO screening, reference or decision deadlines do not qualify.
    role = (
        "Submission of Application Documents and Examination Fee Payment "
        "(via Online Application System)"
    )
    candidates = []
    incomplete = False
    for table in parser.tables:
        for row in table:
            if len(row) != 2 or row[1] != role:
                continue
            endpoints = re.split(r"[～〜–—]|\bto\b", row[0], flags=re.I)
            if len(endpoints) != 2:
                incomplete = True
                continue
            closing = endpoints[1].strip()
            match = date_pattern.match(closing)
            day = parse_date(match) if match else None
            opening = endpoints[0].strip()
            opening_match = date_pattern.fullmatch(opening)
            opening_day = parse_date(opening_match) if opening_match else None
            if day is None or not re.fullmatch(
                r"\s*[“\"']?Strict Deadline[”\"']?\s*", closing[match.end():], re.I,
            ) or (
                opening_match is not None and (opening_day is None or opening_day > day)
            ) or (
                opening_match is None and not _YEARLESS_OPEN.fullmatch(opening)
            ):
                incomplete = True
                continue
            if now.date() <= day <= date(now.year + 2, 12, 31):
                # Preserve the university's actual date/role text, including
                # its time and weekday; do not synthesize an inferred year.
                candidates.append((day.isoformat(), f"{row[0]} — {row[1]}"[:180]))
    if len({day for day, _ in candidates}) > 1 or (candidates and incomplete):
        return "ambiguous_deadline", None, None
    if candidates:
        return "verified", candidates[0][0], candidates[0][1]
    return empty
