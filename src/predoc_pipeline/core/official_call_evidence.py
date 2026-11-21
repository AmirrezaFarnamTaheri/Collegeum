"""Fail-closed official PhD funding evidence shared by publisher and watchdog.

This module is pure standard library. It neither fetches URLs nor sends posts.
Every publication/recovery decision should pass through the same policy.
"""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from .official_call_rules import call_key

_OFFICIAL_KINDS = frozenset({
    "phd_scholarship", "phd_studentship", "phd_fellowship", "phd_bursary",
})
_OFFICIAL_COUNTRIES = frozenset({
    "UK", "GB", "ES", "DE", "FI", "FR", "NL", "IT", "SE", "NO", "DK",
    "CH", "AT", "BE",
})
_OFFICIAL_TITLE = re.compile(r"\b(?:ph\.?\s*d\.?|doctoral)\b", re.I)
_OFFICIAL_DATE = re.compile(r"20\d{2}-\d{2}-\d{2}\Z")
_DATE_IN_TEXT = re.compile(
    r"\b(?P<iso>20\d{2}-\d{2}-\d{2})\b|"
    r"\b(?P<d1>\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(?P<m1>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s*,?\s*(?P<y1>20\d{2})\b|"
    r"\b(?P<m2>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
    r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+(?P<d2>\d{1,2})"
    r"(?:st|nd|rd|th)?\s*,?\s*(?P<y2>20\d{2})\b",
    re.I,
)
_DEADLINE_CONTEXT = re.compile(r"\b(?:by|before|deadline|close|closing|due)\b", re.I)
_STABLE_OFFICIAL_FIELDS = (
    "deadline_iso", "deadline_kind", "kind", "institution", "country_code",
    "title", "recommended_admission_iso", "posting_group",
    "posting_group_expected", "subject_scope", "eligibility_scope",
    "funding_scope", "location_evidence", "location_evidence_url", "evidence_url",
)


def _official_host(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme != "https" or not parsed.hostname or not parsed.path
            or parsed.username or parsed.password or port not in (None, 443)
            or parsed.query or parsed.fragment):
        return None
    return parsed.hostname.lower().removeprefix("www.")


def _checked_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _excerpt_date_matches(excerpt: Any, expected: date) -> bool:
    """Require the full funding deadline, not only a year or a second date."""
    if (not isinstance(excerpt, str) or len(excerpt) > 500
            or not _DEADLINE_CONTEXT.search(excerpt)):
        return False
    parsed: set[date] = set()
    matched = False
    months = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
              "oct", "nov", "dec")
    for found in _DATE_IN_TEXT.finditer(excerpt):
        matched = True
        try:
            if found.group("iso"):
                day = date.fromisoformat(found.group("iso"))
            else:
                month = (found.group("m1") or found.group("m2")).lower()[:3]
                day = date(
                    int(found.group("y1") or found.group("y2")),
                    months.index(month) + 1,
                    int(found.group("d1") or found.group("d2")),
                )
        except (ValueError, TypeError):
            return False
        parsed.add(day)
    return matched and parsed == {expected}


def _location_verified(row: dict[str, Any], host: str) -> bool:
    country = row.get("country_code")
    if country not in _OFFICIAL_COUNTRIES:
        return False
    if row.get("location_evidence_url") != row.get("official_url"):
        return False
    evidence = row.get("location_evidence")
    if not isinstance(evidence, str):
        return False
    national = "uk" if country in {"UK", "GB"} else country.lower()
    if host.endswith("." + national):
        return evidence == f"{country}: official national institutional domain {host}"
    # Exact reviewed institutional body evidence, never a generic .edu guess.
    return (country == "ES" and host == "ieb.ub.edu" and evidence in {
        "ES: official postal address 08034 Barcelona and telephone +34",
        "ES: official IEB and University of Barcelona institutional identifiers",
    })


def _official_source_provenance(catalog: dict[str, Any]) -> dict[str, Any] | None:
    """Bind generated observations to reviewed source summaries.

    Only synthetic fixtures without generated_at use the legacy lightweight
    contract. Removing source summaries from a generated catalogue must not
    bypass the institutional-provenance check.
    """
    if "generated_at" not in catalog:
        return None
    if _checked_utc(catalog["generated_at"]) is None:
        return {}
    sources = catalog.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= 20:
        return {}
    indexed: dict[str, Any] = {}
    for item in sources:
        if not isinstance(item, dict):
            return {}
        name = item.get("id")
        if (not isinstance(name, str) or name in indexed
                or _official_host(item.get("index_url")) is None
                or not isinstance(item.get("institution"), str)
                or item.get("mode") not in {"index", "detail"}):
            return {}
        indexed[name] = item
    return indexed


def eligible_official_calls(catalog: Any, *, now: datetime) -> list[dict[str, Any]]:
    """One shared, fail-closed evidence gate for publication and recovery.

    Inconsistent duplicates and insufficient official-source provenance are
    held, not overwritten by whichever row happens to appear last.
    """
    if (now.tzinfo is None or not isinstance(catalog, dict)
            or catalog.get("kind") != "official_phd_call_observations"
            or catalog.get("version") != 1
            or not isinstance(catalog.get("calls"), list)
            or len(catalog["calls"]) > 100):
        return []
    now = now.astimezone(UTC)
    sources = _official_source_provenance(catalog)
    if "generated_at" in catalog and not sources:
        return []
    matches: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    for row in catalog["calls"]:
        if not isinstance(row, dict) or row.get("status") != "verified":
            continue
        kind = row.get("kind")
        year = row.get("intake_year")
        if (kind not in _OFFICIAL_KINDS
                or row.get("deadline_kind") not in {"scholarship", "funding"}
                or type(year) is not int or not now.year <= year <= now.year + 2):
            continue
        checked = _checked_utc(row.get("checked_at"))
        if checked is None or checked > now or now - checked > timedelta(days=14):
            continue
        raw_deadline = row.get("deadline_iso")
        if not isinstance(raw_deadline, str) or not _OFFICIAL_DATE.fullmatch(raw_deadline):
            continue
        try:
            deadline = date.fromisoformat(raw_deadline)
        except ValueError:
            continue
        if (not now.date() <= deadline <= (now + timedelta(days=366)).date()
                or not deadline.year <= year <= deadline.year + 2):
            continue
        recommendation = row.get("recommended_admission_iso")
        if recommendation is not None:
            if (not isinstance(recommendation, str)
                    or not _OFFICIAL_DATE.fullmatch(recommendation)):
                continue
            try:
                if date.fromisoformat(recommendation) > deadline:
                    continue
            except ValueError:
                continue
        institution = row.get("institution")
        if not isinstance(institution, str) or not 5 <= len(institution) <= 120:
            continue
        host = _official_host(row.get("official_url"))
        if (host is None or row.get("official_url") != row.get("evidence_url")
                or not _location_verified(row, host)):
            continue
        if sources is not None:
            source = sources.get(row.get("source_id"))
            if (source is None or source.get("status") not in {"ok", "partial"}
                    or source.get("institution") != institution
                    or _official_host(source.get("index_url")) != host):
                continue
        title = row.get("title")
        if (not isinstance(title, str) or not _OFFICIAL_TITLE.search(title)
                or not _excerpt_date_matches(row.get("evidence_excerpt"), deadline)):
            continue
        key = call_key(row)
        if key in conflicts:
            continue
        previous = matches.get(key)
        if previous is not None and any(
            previous.get(field) != row.get(field) for field in _STABLE_OFFICIAL_FIELDS
        ):
            conflicts.add(key)
            matches.pop(key, None)
            continue
        matches[key] = row
    return sorted(matches.values(), key=lambda row: (
        row["deadline_iso"], row["institution"], row["official_url"],
    ))
