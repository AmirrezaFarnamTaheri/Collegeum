"""Conservative adapters for independently reviewed US Economics PhD sources.

The adapters resolve programme identity and deadline roles in the university's
own structured HTML. They never supply calendar dates, infer a deadline year,
or authorize a network request. The caller retains robots, HTTPS, freshness,
and cross-page conflict checks.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import date, datetime
from typing import Protocol
from urllib.parse import urljoin, urlsplit


class _Page(Protocol):
    headings: list[str]
    tagged_blocks: list[tuple[str, str]]
    links: list[tuple[str, str]]

    def text(self) -> str: ...


_PHD = r"Ph\.?\s?D\.?"
_EMPTY = ("no_explicit_deadline", None, None)
_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_YEARLESS_DATE = re.compile(
    rf"\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b|"
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\b|"
    r"(?<!\d)\d{1,2}[./]\d{1,2}(?!\d)", re.I,
)
_TIME_SUFFIX = re.compile(
    r"at\s+(?:2[0-3]|[01]?\d)(?::[0-5]\d)?\s*(?:[ap]\.?m\.?)?"
    r"(?:\s+(?:(?:Eastern|Central|Mountain|Pacific)(?:\s+(?:Standard|Daylight))?"
    r"\s+Time|EST|EDT|CST|CDT|MST|MDT|PST|PDT|ET|CT|MT|PT|UTC|GMT))?", re.I,
)


def _unambiguous_suffix(suffix: str, date_pattern: re.Pattern[str]) -> bool:
    """Permit the reviewed clock suffix and ordinary prose after a sentence.

    A second date, applicant-specific value or unresolved later cutoff cannot
    be dropped merely because the first date followed the expected label.
    Unknown text attached to the same date value remains unconfirmed.
    """
    remainder = suffix.strip()
    clock = _TIME_SUFFIX.match(remainder)
    clock_ends_sentence = bool(clock and clock.group().endswith("."))
    if clock:
        remainder = remainder[clock.end():].strip()
    if not remainder:
        return True
    if remainder[0] in ".!?":
        remainder = remainder[1:].strip()
    elif not clock_ends_sentence:
        return False
    if date_pattern.search(remainder) or _YEARLESS_DATE.search(remainder):
        return False
    if re.search(
        r"\b(?:domestic|international|overseas|local)\s+(?:applicants|students)\s*:",
        remainder, re.I,
    ):
        return False
    has_cutoff = re.search(r"\b(?:deadline|cutoff|applications?\s+(?:close|due))", remainder, re.I)
    unresolved = re.search(
        r"\b(?:tba|tbd|pending|announc\w*|later|earlier|alternate|different|"
        r"separate|another|extend\w*)\b", remainder, re.I,
    )
    return not (has_cutoff and unresolved)


def _result(
    blocks: Iterable[str], label: str, *, now: datetime,
    date_pattern: re.Pattern[str], parse_date: Callable[[re.Match[str]], date | None],
    scope: str,
) -> tuple[str, str | None, str | None]:
    """Read the full date immediately after its role, never a neighboring date."""
    dates: list[tuple[str, str]] = []
    incomplete = False
    ambiguous_suffix = False
    for block in blocks:
        for marker in re.finditer(label, block, re.I):
            remainder = block[marker.end():].lstrip(" :\u2013\u2014-")
            match = date_pattern.match(remainder)
            proposed = parse_date(match) if match else None
            if proposed is None:
                incomplete = True
                continue
            if not now.date() <= proposed <= date(now.year + 2, 12, 31):
                continue
            if not _unambiguous_suffix(remainder[match.end():], date_pattern):
                ambiguous_suffix = True
                continue
            # The scope names are supported by each adapter's identity checks.
            # Keep the source's own role and date together in the public excerpt.
            excerpt = f"{scope}: {block[marker.start():]}"[:180]
            dates.append((proposed.isoformat(), excerpt))
    if ambiguous_suffix or len({day for day, _ in dates}) > 1 or (dates and incomplete):
        return "ambiguous_deadline", None, None
    if dates:
        return "verified", dates[0][0], dates[0][1]
    return _EMPTY


def _cmu(parser: _Page, *, source_url: str, **kwargs):
    # Official source reviewed 2026-11-24:
    # https://www.cmu.edu/tepper/programs/phd/admissions
    # This shared doctoral application page explicitly links the Economics
    # doctoral route. An MBA or another school's similarly named page cannot
    # provide its date.
    if not any(re.fullmatch(rf"{_PHD}\s+Admissions", h, re.I) for h in parser.headings):
        return _EMPTY
    economics_route = False
    for href, label in parser.links:
        linked = urlsplit(urljoin(source_url, href))
        if (
            linked.scheme == "https"
            and (linked.hostname or "").removeprefix("www.") == "cmu.edu"
            and linked.path.rstrip("/") == "/tepper/programs/phd/economics"
            and label.strip() == "Economics"
        ):
            economics_route = True
    text = parser.text()
    if not economics_route or not re.search(
        rf"apply to the\s+{_PHD}\s+program at the Tepper School of Business", text, re.I,
    ):
        return _EMPTY
    blocks: list[str] = []
    active = False
    for tag, block in parser.tagged_blocks:
        if tag == "h2":
            active = bool(re.fullmatch(r"Application Instructions", block, re.I))
        elif active and tag == "p":
            blocks.append(block)
    return _result(
        blocks, r"\bThe application site will remain open until\s*",
        scope="Tepper Economics Ph.D. application", **kwargs,
    )


def _notre_dame(parser: _Page, **kwargs):
    # https://economics.nd.edu/graduate/admissions-and-funding/
    # The dated standalone deadline precedes the PhD application requirements;
    # a later historical timeline describes prior years and is not evidence.
    if not any(h == "Admissions and Funding" for h in parser.headings):
        return _EMPTY
    text = parser.text()
    if not (
        re.search(r"\bDepartment of Economics\b", text)
        and re.search(
            rf"materials are required for application to the\s+{_PHD}\s+program", text, re.I,
        )
    ):
        return _EMPTY
    blocks: list[str] = []
    in_body = False
    for tag, block in parser.tagged_blocks:
        if tag == "h1":
            in_body = block == "Admissions and Funding"
        elif in_body and tag == "h2":
            break
        elif in_body and tag == "p" and re.match(r"^Deadline\s*:", block, re.I):
            blocks.append(block)
    return _result(blocks, r"^Deadline\s*:\s*", scope="Economics Ph.D. application", **kwargs)


def _washu(parser: _Page, **kwargs):
    # https://gradstudies.artsci.washu.edu/browse/economics
    # Separate PhD and MA headings carry distinct application deadlines.
    if "Economics" not in parser.headings or not re.search(
        r"\bdoctoral program\b[^.]{0,200}\bPhD students\b", parser.text(), re.I,
    ):
        return _EMPTY
    blocks: list[str] = []
    active = False
    for tag, block in parser.tagged_blocks:
        if tag in {"h2", "h3", "h4"} and re.fullmatch(
            r"Application deadline\s*:", block, re.I,
        ):
            active = True
        elif active and tag == "h4" and re.match(rf"^{_PHD}\s*[-\u2013\u2014]", block, re.I):
            blocks.append(block)
        elif active and (
            (tag == "h4" and not re.match(r"^MA\s*[-\u2013\u2014]", block))
            or tag in {"h1", "h2", "h3"}
        ):
            active = False
    return _result(
        blocks, rf"^{_PHD}\s*[-\u2013\u2014]\s*",
        scope="Economics application deadline", **kwargs,
    )


def _penn(parser: _Page, **kwargs):
    # https://economics.sas.upenn.edu/graduate/prospective-students/application-guidelines
    # The general submission cutoff is separate from fellowship instructions.
    # The doctoral identity appears later in the same departmental page.
    if not (
        "Application Guidelines" in parser.headings
        and re.search(r"\bDepartment of Economics\b", parser.text())
        and re.search(
            rf"Admissions Information to the\s+{_PHD}\s+Program in Economics",
            parser.text(), re.I,
        )
    ):
        return _EMPTY
    blocks: list[str] = []
    active = False
    for tag, block in parser.tagged_blocks:
        if tag == "h1":
            active = block == "Application Guidelines"
        elif active and tag == "p":
            blocks.append(block)
    return _result(
        blocks, r"\bThe deadline to submit your application is\s*",
        scope="Economics Ph.D.", **kwargs,
    )


def collect_deadline(
    parser: _Page, *, now: datetime, source_url: str | None,
    date_pattern: re.Pattern[str], parse_date: Callable[[re.Match[str]], date | None],
) -> tuple[str, str | None, str | None] | None:
    """Return None for an unhandled route; handled routes always fail closed."""
    parsed = urlsplit(source_url or "")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    routes = {
        ("cmu.edu", "/tepper/programs/phd/admissions"): _cmu,
        ("cmu.edu", "/tepper/programs/phd/admissions/index.html"): _cmu,
        ("economics.nd.edu", "/graduate/admissions-and-funding"): _notre_dame,
        ("gradstudies.artsci.washu.edu", "/browse/economics"): _washu,
        (
            "economics.sas.upenn.edu",
            "/graduate/prospective-students/application-guidelines",
        ): _penn,
    }
    adapter = routes.get((host, path))
    if adapter is None:
        return None
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return _EMPTY
    kwargs = {"now": now, "date_pattern": date_pattern, "parse_date": parse_date}
    if adapter is _cmu:
        return adapter(parser, source_url=source_url, **kwargs)
    return adapter(parser, **kwargs)
