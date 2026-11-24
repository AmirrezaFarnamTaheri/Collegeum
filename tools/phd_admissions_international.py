"""Explicit university admissions tables missed by adjacent English date matching.

These adapters bind the date to the named doctoral programme and its actual
application column. They never supply a missing year or use search snippets.
The caller remains responsible for HTTPS, robots, response integrity and age.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

Result = tuple[str, str | None, str | None]
NO_DATE: Result = ("no_explicit_deadline", None, None)
AMBIGUOUS: Result = ("ambiguous_deadline", None, None)


def _result(
    candidates: list[tuple[date, str]], now: datetime, *, incomplete: bool = False,
) -> Result:
    current = [(day, excerpt) for day, excerpt in candidates
               if now.date() <= day <= date(now.year + 2, 12, 31)]
    if len({day for day, _ in current}) > 1 or (current and incomplete):
        return AMBIGUOUS
    if current:
        day, excerpt = current[0]
        return "verified", day.isoformat(), excerpt[:180]
    return NO_DATE


def _keio_endpoint(value: str) -> str:
    """Remove only the time prefix actually used by Keio's timetable."""
    return re.sub(
        r"^(?:0?[1-9]|1[0-2]):[0-5]\d\s*(?:a\.m\.|p\.m\.)\s+on\s+",
        "", value.strip(), flags=re.I,
    )


# The opening endpoint on the reviewed page has no year; the closing endpoint
# supplies its own explicit year. Recognise the opening's shape without assigning
# it a year or allowing extra application dates to hide in either endpoint.
_KEIO_YEARLESS_OPEN = re.compile(
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+(?:0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?"
    r"(?:\s*\((?:Mon(?:day)?|Tue(?:sday)?|Wed(?:nesday)?|"
    r"Thu(?:rs(?:day)?)?|Fri(?:day)?|Sat(?:urday)?|Sun(?:day)?)\))?",
    re.I,
)


def collect_deadline(
    parser: Any, *, now: datetime, source_url: str | None,
    date_pattern: re.Pattern[str], parse_date: Callable[[re.Match[str]], date | None],
) -> Result | None:
    """Return None only for routes that this module does not handle."""
    source = urlsplit(source_url or "")
    host = (source.hostname or "").lower().removeprefix("www.")
    path = source.path.rstrip("/")
    text = parser.text()
    candidates: list[tuple[date, str]] = []

    # https://applygrad.mcmaster.ca/portal/start_your_app?cmd=get_results&selectedterm=sept
    # The public application inventory has a blank Apply Now column. Remove
    # only that exact button cell; do not shift arbitrary missing table cells.
    if host == "applygrad.mcmaster.ca" and path == "/portal/start_your_app":
        for table in parser.tables:
            header = next((row for row in table if row == [
                "Program", "Open Date", "Domestic Close Date",
                "International Close Date", "Website",
            ]), None)
            if header is None:
                continue
            for row in table:
                if not row or row[0] != "Economics PhD":
                    continue
                cells = list(row)
                if len(cells) == 6 and cells[1] == "Apply Now":
                    cells.pop(1)
                if len(cells) != len(header):
                    return NO_DATE
                matches = [date_pattern.fullmatch(value) for value in cells[1:4]]
                if any(match is None for match in matches):
                    return NO_DATE
                days = [parse_date(match) for match in matches if match is not None]
                if any(day is None for day in days):
                    return NO_DATE
                opened, domestic, international = days
                if domestic < opened or international < opened:
                    return NO_DATE
                if opened > now.date():
                    continue
                if domestic != international:
                    return AMBIGUOUS
                excerpt = (
                    "Economics PhD — Domestic Close Date: " + cells[2]
                    + "; International Close Date: " + cells[3]
                    + " [official application table]"
                )
                candidates.append((domestic, excerpt))
        return _result(candidates, now)

    # https://www.keio.ac.jp/en/admissions/grad/doctoral/gsecon/
    # Online registration is the application step. Payment, paper uploads,
    # screening, decisions and post-offer enrolment are different deadlines.
    if host == "keio.ac.jp" and path in {
        "/en/admissions/grad/doctoral/gsecon", "/en/grad-admissions/doctoral/gsecon",
    }:
        if not any(re.fullmatch(
            r"General Admissions for Doctoral Program \(Graduate School of Economics\)",
            heading, re.I,
        ) for heading in parser.headings):
            return NO_DATE
        incomplete = False
        for table in parser.tables:
            if not table or not table[0] or table[0][0] != "Application Period":
                continue
            if not any(row and row[0] == "Online Registration" for row in table[1:]):
                incomplete = True
                continue
            for row in table:
                if not row or row[0] != "Online Registration":
                    continue
                if len(row) != len(table[0]):
                    return NO_DATE
                for value in row[1:]:
                    endpoints = re.split(r"\s+[-–—]\s+|[～〜]", value)
                    if len(endpoints) != 2:
                        incomplete = True
                        continue
                    opened, closed = map(_keio_endpoint, endpoints)
                    closing = date_pattern.fullmatch(closed)
                    day = parse_date(closing) if closing else None
                    opening = date_pattern.fullmatch(opened)
                    opening_day = parse_date(opening) if opening else None
                    if day is None or (
                        opening is not None and (opening_day is None or opening_day > day)
                    ) or (opening is None and not _KEIO_YEARLESS_OPEN.fullmatch(opened)):
                        incomplete = True
                        continue
                    candidates.append((day,
                        "Economics Doctoral Program — Online Registration: "
                        + value + " [application period]"))
        return _result(candidates, now, incomplete=incomplete)

    # https://admission.umontreal.ca/programmes/doctorat-en-sciences-economiques/
    # French month names and a spaced superscript ordinal still contain an
    # explicit full year. The closing date follows 'au' in the admission range.
    if host == "admission.umontreal.ca" and path == "/programmes/doctorat-en-sciences-economiques":
        if "Doctorat en sciences économiques" not in parser.headings:
            return NO_DATE
        labels = list(re.finditer(
            r"Dates limites\s+Déposer la demande d['’]admission\s+", text,
        ))
        incomplete = False
        for index, label in enumerate(labels):
            end = labels[index + 1].start() if index + 1 < len(labels) else len(text)
            section = text[label.end():end]
            beginning = re.match(r"Du\s+", section)
            opened = date_pattern.match(section, beginning.end()) if beginning else None
            separator = re.match(r"\s+au\s+", section[opened.end():]) if opened else None
            closing = date_pattern.match(
                section, opened.end() + separator.end(),
            ) if opened and separator else None
            if opened is None or closing is None:
                incomplete = True
                continue
            # The actual deadline card ends here; a second cutoff or other
            # unrecognised range suffix cannot be silently dropped.
            suffix = section[closing.end():].strip()
            first, last = parse_date(opened), parse_date(closing)
            if (
                first is None or last is None or first > last
                or (suffix and not re.match(r"Offert au campus\b", suffix))
            ):
                incomplete = True
                continue
            excerpt = text[label.start():label.end() + closing.end()]
            candidates.append((last, excerpt))
        return _result(candidates, now, incomplete=incomplete)

    # https://prog-crs.hkust.edu.hk/pgprog/2027-28/mphil-phd-econ
    # The official degree catalogue explicitly requires PhD applications and
    # lists four applicant/mode cutoffs. HKPFS funding dates cannot substitute.
    if host == "prog-crs.hkust.edu.hk" and re.fullmatch(
        r"/pgprog/20\d{2}-\d{2}/mphil-phd-econ", path,
    ):
        if not (
            "Doctor of Philosophy in Economics" in text
            and "Offering Unit Department of Economics" in text
            and "Applicants should apply for the PhD program" in text
            and "Application Deadlines" in text
        ):
            return NO_DATE
        sections = list(re.finditer(r"For (20\d{2})/(\d{2}) Fall Term Intake\b", text))
        incomplete = False
        for index, section in enumerate(sections):
            if f"/{section.group(1)}-{section.group(2)}/" not in path:
                continue
            end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
            raw_section = text[section.end():end]
            cutoff = raw_section.find("MPhil program is only available")
            if cutoff < 0:
                incomplete = True
                continue
            groups = re.fullmatch(
                r"\s*(?:\(commencing in [A-Za-z]+ " + section.group(1) + r"\):\s*)?"
                r"Non-local Applicants\*?\s+(.+?)\s+Local Applicants\s+(.+?)\s*",
                raw_section[:cutoff], re.S,
            )
            if groups is None:
                incomplete = True
                continue
            parsed: list[tuple[date, str]] = []
            for applicant in groups.groups():
                modes = re.fullmatch(r"Full-time:\s*(.+?)\s+Part-time:\s*(.+)", applicant)
                if modes is None:
                    incomplete = True
                    continue
                for raw in modes.groups():
                    match = date_pattern.fullmatch(raw.strip().removesuffix("^").strip())
                    day = parse_date(match) if match else None
                    if day is None:
                        incomplete = True
                        continue
                    parsed.append((day, match.group()))
            if len(parsed) != 4:
                continue
            if len({day for day, _ in parsed}) != 1:
                return AMBIGUOUS
            day, raw = parsed[0]
            candidates.append((day,
                "Economics PhD — Fall Term Intake Application Deadlines: "
                + "Non-local / Local Applicants, Full-time / Part-time: " + raw))
        return _result(candidates, now, incomplete=incomplete)

    # York publishes separate MA and PhD sections. Recognise the actual PhD
    # dates, but never silently choose one citizenship group's deadline.
    if host == "futurestudents.yorku.ca" and path == "/graduate/programs/economics":
        if "Economics" not in parser.headings:
            return NO_DATE
        sections = list(re.finditer(r"\bPhD Program Component\(s\)", text))
        incomplete = False
        for index, section in enumerate(sections):
            end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
            raw_section = text[section.end():end]
            cutoff = raw_section.find("English Proficiency")
            if cutoff < 0:
                incomplete = True
                continue
            raw_section = raw_section[:cutoff]
            labels = list(re.finditer(
                r"Deadline - Fall \((Domestic|International) Applicants Only\)\s+",
                raw_section,
            ))
            if {label.group(1) for label in labels} != {"Domestic", "International"}:
                incomplete = True
                continue
            dates = []
            printed = {}
            for label_index, label in enumerate(labels):
                field_end = (
                    labels[label_index + 1].start()
                    if label_index + 1 < len(labels) else len(raw_section)
                )
                full = date_pattern.fullmatch(raw_section[label.end():field_end].strip())
                day = parse_date(full) if full else None
                if day is None:
                    incomplete = True
                    continue
                dates.append(day)
                printed.setdefault(
                    label.group(1), raw_section[label.start():field_end].strip(),
                )
            if len(dates) != len(labels):
                continue
            if len(set(dates)) > 1:
                return AMBIGUOUS
            candidates.append((
                dates[0], "Economics PhD — " + printed["Domestic"] + "; "
                + printed["International"],
            ))
        return _result(candidates, now, incomplete=incomplete)
    return None
