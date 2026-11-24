"""Role-aware deadlines from reviewed European doctoral admissions pages.

The routes here were checked against official HTML on 2026-11-24.  Each
adapter requires the programme identity and the deadline's application role
on the fetched page.  These are extraction rules, never stored date overrides.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urlsplit

_TIME = r"(?:[01]?\d|2[0-3]):[0-5]\d"
_ZONE = r"(?:CET|CEST|Central European (?:Summer )?Time)"
_TIME_WITH_ZONE = rf"{_TIME}(?:\s*,?\s*{_ZONE})?"
_SCALAR_SUFFIX = re.compile(
    rf"\s*[,;]?\s*(?:{_TIME_WITH_ZONE}|\(\s*{_TIME_WITH_ZONE}\s*\))?\s*[.;]?\s*",
    re.I,
)


def _sections(parser, title: str) -> list[list[str]]:
    """Read every matching section, including repeated or nested headings.

    Each section retains its own peer/parent boundary.  Stopping after the
    first section could silently discard a second, conflicting application
    deadline elsewhere on the same official page.
    """
    sections: list[list[str]] = []
    for index, (tag, value) in enumerate(parser.tagged_blocks):
        if not re.fullmatch(r"h[1-6]", tag) or not re.fullmatch(title, value, re.I):
            continue
        level = int(tag[1])
        blocks: list[str] = []
        for later_tag, later_value in parser.tagged_blocks[index + 1:]:
            heading = int(later_tag[1]) if re.fullmatch(r"h[1-6]", later_tag) else None
            if heading is not None and heading <= level:
                break
            blocks.append(later_value)
        sections.append(blocks)
    return sections


def _section(parser, title: str) -> list[str]:
    return [block for section in _sections(parser, title) for block in section]


def _result(candidates: list[tuple[date | None, str]], *, now: datetime):
    # A relevant label with an unreadable or yearless value is evidence of
    # incomplete application information, not permission to pick another date.
    incomplete = any(day is None for day, _ in candidates)
    current = [(day, excerpt) for day, excerpt in candidates
               if day is not None and now.date() <= day <= date(now.year + 2, 12, 31)]
    if len({day for day, _ in current}) > 1 or (current and incomplete):
        return "ambiguous_deadline", None, None
    if current:
        day, excerpt = current[0]
        return "verified", day.isoformat(), excerpt[:180]
    return "no_explicit_deadline", None, None


def _labelled_dates(blocks, label, *, date_pattern, parse_date, subject=""):
    candidates = []
    for block in blocks:
        roles = list(re.finditer(label, block, re.I))
        for index, role in enumerate(roles):
            # Require the date immediately after its own label.  Searching
            # ahead could borrow a later funding/test date after a yearless one.
            match = date_pattern.match(block, role.end())
            if match is None or (day := parse_date(match)) is None:
                candidates.append((None, ""))
                continue
            excerpt = subject + block[role.start():match.end()]
            candidates.append((day, excerpt))
            end = roles[index + 1].start() if index + 1 < len(roles) else len(block)
            tail = block[match.end():end]
            # Trinity prints funding's separate label in the same paragraph.
            # It is outside this application value even when its year is absent.
            funding = re.search(r"\bDeadline for funding consideration\s*:", tail, re.I)
            if funding is not None:
                tail = tail[:funding.start()]
            # These reviewed fields hold one date, sometimes with a time and
            # timezone.  Unknown trailing prose may introduce applicant
            # restrictions or an incomplete second cutoff.  Do not infer its
            # meaning merely because it lacks an "or"/"and" connector.
            if _SCALAR_SUFFIX.fullmatch(tail) is None:
                candidates.append((None, ""))
    return candidates


def collect_deadline(parser, *, now, source_url, date_pattern, parse_date):
    """Return None for an unhandled route; handled pages always fail closed."""
    source = urlsplit(source_url or "")
    host = (source.hostname or "").lower().removeprefix("www.")
    path = source.path.rstrip("/")
    text = parser.text()
    empty = ("no_explicit_deadline", None, None)
    if source.scheme != "https":
        return None

    # CEU explicitly applies one deadline to all doctoral applicants and
    # links the Economics PhD's requirements from this doctoral-only page.
    # Source: https://www.ceu.edu/admissions/doctoral
    if host == "ceu.edu" and path == "/admissions/doctoral":
        economics = any(
            label.strip() == "Economics"
            and (target := urlsplit(href)).scheme == "https"
            and (target.hostname or "").removeprefix("www.") == host
            and target.path.rstrip("/") == "/academics/degrees/phd-economics"
            for href, label in parser.links
        )
        if not (economics and any(
            re.fullmatch(r"Apply to a Doctoral Program at CEU", h, re.I)
            for h in parser.headings
        )):
            return empty
        sections = _sections(parser, r"Doctoral Degree at CEU\s*[-–]\s*Application Deadlines")
        if not sections or any(
            not any(re.fullmatch(r"Applicable to:\s*all applicants", b, re.I)
                    for b in blocks)
            for blocks in sections
        ):
            return empty
        blocks = [block for section in sections for block in section]
        return _result(_labelled_dates(
            # This is a bare application field in CEU's doctoral section.
            # A qualified "Funding deadline" or "Document deadline" field
            # must not inherit its application role from the section title.
            blocks, r"(?:^|(?<=[.;]))\s*Deadline\s*:\s*", date_pattern=date_pattern,
            parse_date=parse_date, subject="CEU doctoral applications (Economics included): ",
        ), now=now)

    # The DIW Graduate Center explains on this same page that its economics
    # training leads to a PhD.  The deadline is in its application schedule,
    # not in the neighbouring reference-letter or test FAQs.
    # Source: https://www.diw.de/en/diw_01.c.799242.en/application.html
    if host == "diw.de" and re.fullmatch(
        r"/(?:de|en)/diw_01\.c\.799242\.(?:de|en)/application\.html", path,
    ):
        if not (
            any(h == "Application" for h in parser.headings)
            and re.search(r"DIW Graduate Center offers[^.]{0,100}training in economics", text)
            and re.search(r"obtain a PhD from one of Berlin[’']s universities", text)
        ):
            return empty
        return _result(_labelled_dates(
            _section(parser, r"Application Schedule"),
            r"(?:^|(?<=[.;]))\s*Deadline for applications\s*:\s*", date_pattern=date_pattern,
            parse_date=parse_date, subject="DIW economics doctoral programme: ",
        ), now=now)

    # The active PhD vacancy list explicitly includes the Economics
    # department and identifies the next common application deadline.
    # Source: https://www.nhh.no/en/study-programmes/phd-programme-at-nhh/vacant-phd-positions/
    if host == "nhh.no" and path == (
        "/en/study-programmes/phd-programme-at-nhh/vacant-phd-positions"
    ):
        if not (
            any(h == "Vacant PhD positions" for h in parser.headings)
            and any(re.fullmatch(
                r"PhD Research Scholar positions\s*[-–]\s*Department of Economics", b,
                re.I,
            ) for b in parser.blocks)
            and re.search(r"NHH is seeking[^.]{0,120}our PhD Programme", text, re.I)
        ):
            return empty
        blocks = [b for b in parser.blocks if re.match(
            r"^The main application deadline is normally\b", b, re.I,
        )]
        return _result(_labelled_dates(
            blocks, r"\bour next deadline is\s*", date_pattern=date_pattern,
            parse_date=parse_date, subject="NHH Economics PhD application: ",
        ), now=now)

    # Cologne offers distinct MSc and PhD entry stages.  Only a sentence
    # explicitly naming admission to the PhD Stage supplies its closing date.
    # Source: https://cgs.uni-koeln.de/en/economics/phd-programme/application
    if host == "cgs.uni-koeln.de" and path in {
        "/en/economics/phd-programme/application",
        "/en/doctoral-phd-programmes/phd-programme-in-economics/admission",
    }:
        if not any(
            tag in {"h1", "h2", "h3"}
            and re.fullmatch(r"Application to the PhD Programme in Economics", b, re.I)
            for tag, b in parser.tagged_blocks
        ):
            return empty
        blocks = [b for b in parser.blocks if re.match(
            r"^Applications for admission to the PhD Stage\b", b, re.I,
        )]
        return _result(_labelled_dates(
            blocks, r"\buntil\s+", date_pattern=date_pattern, parse_date=parse_date,
            subject="Economics PhD-stage application cutoff: ",
        ), now=now)

    # Edinburgh places the programme start and application cutoff in adjacent
    # columns.  Do not flatten both dates under the deadline header.
    # Source: https://study.ed.ac.uk/programmes/postgraduate-research/278-economics
    if host == "study.ed.ac.uk" and path == (
        "/programmes/postgraduate-research/278-economics"
    ):
        if not any(re.fullmatch(r"Economics PhD with Integrated Study", h, re.I)
                   for h in parser.headings):
            return empty
        candidates = []
        for table in parser.tables:
            if not table or table[0] != ["Programme start date", "Application deadline"]:
                continue
            for row in table[1:]:
                start = date_pattern.fullmatch(row[0]) if row else None
                start_day = parse_date(start) if start is not None else None
                # A past intake cannot supply a current application cutoff.
                # Unknown starts remain relevant because their cycle is unknown.
                if start_day is not None and start_day < now.date():
                    continue
                deadline = date_pattern.fullmatch(row[1]) if len(row) == 2 else None
                deadline_day = parse_date(deadline) if deadline is not None else None
                if start_day is None or deadline_day is None or deadline_day > start_day:
                    candidates.append((None, ""))
                    continue
                candidates.append((
                    deadline_day,
                    f"Economics PhD application deadline (table): {deadline.group()}",
                ))
        return _result(candidates, now=now)

    # Trinity explicitly distinguishes the PhD application cutoff from the
    # earlier funding consideration date, even inside one HTML paragraph.
    # Source: https://www.tcd.ie/economics/programmes/postgraduate/phd-in-economics-/admission-requirements/
    if host == "tcd.ie" and path == (
        "/economics/programmes/postgraduate/phd-in-economics-/admission-requirements"
    ):
        if not any(
            tag in {"h1", "h2", "h3"}
            and re.fullmatch(r"PhD in Economics:\s*Requirements", b, re.I)
            for tag, b in parser.tagged_blocks
        ):
            return empty
        return _result(_labelled_dates(
            _section(parser, r"Application Deadlines"),
            r"(?:^|(?<=[.;]))\s*Deadline for PhD applications\s*:\s*", date_pattern=date_pattern,
            parse_date=parse_date, subject="Economics: ",
        ), now=now)
    return None
