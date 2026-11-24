"""Read the formal GPEM doctoral application period on Tohoku's own page.

The reviewed doctoral guideline linked by this page explicitly awards a PhD
in Economics or Management.  The programme's earlier pre-application stage is
required and stays visible in the evidence; it is not the formal cutoff.
No dates or years are supplied by this module.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlsplit

_EMPTY = ("no_explicit_deadline", None, None)
_ROUTE = ("econ.tohoku.ac.jp", "/en/gpem/gpem-admission")
_SCHEDULE = re.compile(
    r"Application Schedule for (20\d{2}) Academic Year Foreign Student "
    r"Screening \(October Entrance\)", re.I,
)
_SUFFIX = re.compile(r"(?:,\s*(?:[01]?\d|2[0-3]):[0-5]\d\s*\(JST\))?\s*", re.I)


def _bounded(blocks, index):
    level = int(blocks[index][0][1])
    content = []
    for tag, text in blocks[index + 1:]:
        if re.fullmatch(r"h[1-6]", tag) and int(tag[1]) <= level:
            break
        content.append((tag, text))
    return content


def _period(value, *, date_pattern, parse_date):
    if not isinstance(value, str):
        return None
    endpoints = re.split(r"[～〜–—]|\bto\b|\s+-\s+", value, flags=re.I)
    if len(endpoints) != 2:
        return None
    opening, closing = (part.strip() for part in endpoints)
    first = date_pattern.fullmatch(opening)
    last = date_pattern.match(closing)
    start = parse_date(first) if first else None
    end = parse_date(last) if last else None
    if start is None or end is None or start > end:
        return None
    if _SUFFIX.fullmatch(closing[last.end():]) is None:
        return None
    return start, end, last.group()


def _fields(blocks):
    values = {"Pre application": [], "Application Period": []}
    incomplete = False
    for index, (tag, text) in enumerate(blocks):
        # No nested applicant categories occur in the reviewed doctoral
        # section. An added heading needs explicit interpretation first.
        if re.fullmatch(r"h[1-6]", tag):
            incomplete = True
        if tag != "th":
            continue
        if text not in values:
            if re.match(r"(?:Pre application|Application Period)\b", text, re.I):
                incomplete = True
            continue
        if index + 1 >= len(blocks) or blocks[index + 1][0] != "td":
            incomplete = True
            continue
        if index + 2 < len(blocks) and blocks[index + 2][0] == "td":
            incomplete = True
        values[text].append(blocks[index + 1][1])
    if any(len(set(fields)) != 1 for fields in values.values()):
        incomplete = True
    return values, incomplete


def collect_deadline(parser, *, now, source_url, date_pattern, parse_date):
    """Handle only the reviewed departmental GPEM admission route."""
    source = urlsplit(source_url or "")
    host = (source.hostname or "").lower().removeprefix("www.")
    if (host, source.path.rstrip("/")) != _ROUTE:
        return None
    try:
        safe = (source.scheme == "https" and source.port in (None, 443)
                and source.username is None and source.password is None)
    except ValueError:
        safe = False
    if not safe or "GPEM Admission" not in parser.headings:
        return _EMPTY
    if "Graduate School of Economics and Management / Faculty of Economics, " \
            "Tohoku University" not in parser.text():
        return _EMPTY

    # This exact named doctoral guide distinguishes direct doctoral entry
    # from the separate Master's and internal continuation routes.
    # Reviewed identity source (not an automatic date source):
    # https://www.econ.tohoku.ac.jp/wp/wp-content/uploads/2026/11/
    # 2.GPEM-Guideline_Doctoral_202710.pdf, p. 2, degree statement.
    guide_years = set()
    for href, label in parser.links:
        if label != "Doctoral Program":
            continue
        target = urlsplit(href)
        try:
            safe = (target.scheme == "https" and target.port in (None, 443)
                    and target.username is None and target.password is None
                    and (target.hostname or "").lower().removeprefix("www.") == host)
        except ValueError:
            safe = False
        guide = re.fullmatch(
            r"/wp/wp-content/uploads/20\d{2}/\d{2}/"
            r"\d+\.GPEM-Guideline_Doctoral_(20\d{2})10\.pdf", target.path,
        )
        if safe and guide:
            guide_years.add(int(guide.group(1)))
    if not guide_years:
        return _EMPTY

    candidates = []
    incomplete = False
    blocks = parser.tagged_blocks
    for index, (tag, title) in enumerate(blocks):
        if tag != "h2" or not title.startswith("Application Schedule for "):
            continue
        schedule = _SCHEDULE.fullmatch(title)
        content = _bounded(blocks, index)
        for child, (child_tag, heading) in enumerate(content):
            if child_tag != "h3" or heading != "Doctoral Program":
                continue
            if schedule is None:
                incomplete = True
                continue
            intake = int(schedule.group(1))
            if date(intake, 10, 1) < now.date():
                continue
            if intake not in guide_years:
                incomplete = True
                continue
            fields, problem = _fields(_bounded(content, child))
            if problem:
                incomplete = True
                continue
            prelim = _period(fields["Pre application"][0],
                             date_pattern=date_pattern, parse_date=parse_date)
            formal = _period(fields["Application Period"][0],
                             date_pattern=date_pattern, parse_date=parse_date)
            if prelim is None or formal is None or not (
                prelim[1] <= formal[0] <= formal[1] <= date(intake, 10, 1)
            ):
                incomplete = True
                continue
            if not now.date() <= formal[1] <= date(now.year + 2, 12, 31):
                continue
            excerpt = (
                "GPEM Doctoral Program (Foreign Student Screening): "
                f"Application Period ends {formal[2]}; "
                f"required Pre application ends {prelim[2]}."
            )
            if len(excerpt) > 180:
                incomplete = True
                continue
            candidates.append((formal[1], prelim[1], excerpt))
    if len({(day, prelim) for day, prelim, _ in candidates}) > 1 or (
        candidates and incomplete
    ):
        return "ambiguous_deadline", None, None
    if candidates:
        day, _, excerpt = candidates[0]
        return "verified", day.isoformat(), excerpt
    return _EMPTY
