"""One dependency-free admission evidence gate for Telegram and recovery.

Admissions are not independent PhD funding calls. University query URLs and
application opening dates may be legitimate; a funding-only evidence rule
would wrongly erase verified admissions. No network IO or sends occur here.
"""
from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from .official_call_evidence import _checked_utc, explicit_official_deadline

ISO_DAY = re.compile(r"20\d{2}-\d{2}-\d{2}\Z")
COUNTRY_NAMES = {
    "AT": "Austria", "AU": "Australia", "BE": "Belgium",
    "CA": "Canada", "CH": "Switzerland", "CL": "Chile", "CN": "China",
    "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "ES": "Spain",
    "FI": "Finland", "FR": "France", "GR": "Greece", "HK": "Hong Kong",
    "IE": "Ireland", "IT": "Italy", "JP": "Japan",
    "KR": "South Korea", "MY": "Malaysia", "NL": "Netherlands",
    "NO": "Norway", "NZ": "New Zealand", "PH": "Philippines",
    "PL": "Poland", "PT": "Portugal", "RS": "Serbia",
    "SE": "Sweden", "SG": "Singapore", "TH": "Thailand",
    "TW": "Taiwan", "UK": "United Kingdom", "US": "United States",
    "ZA": "South Africa",
}


def admissions_host(value: Any) -> str | None:
    """University admissions can have approved query-bearing application URLs."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username or parsed.password or port not in (None, 443)):
        return None
    return parsed.hostname.lower().removeprefix("www.")


def _independently_non_us(row: dict[str, Any], host: str) -> bool:
    country = row.get("country_code")
    if not isinstance(country, str) or re.fullmatch(r"[A-Z]{2}", country) is None:
        return False
    if country == "US":
        return False
    national = "uk" if country in {"UK", "GB"} else country.lower()
    if host.endswith("." + national):
        return True
    # A claimed country, generic .org/.eu domain or source list is not proof.
    expected = COUNTRY_NAMES.get(country)
    details = row.get("official_details")
    if not expected or not isinstance(details, dict):
        return False
    fact = details.get("institution_country")
    if (not isinstance(fact, dict) or fact.get("value") != expected
            or fact.get("checked_at") != row.get("checked_at")
            or admissions_host(fact.get("evidence_url")) != host):
        return False
    investigated = row.get("investigated_urls")
    if not isinstance(investigated, list) or fact["evidence_url"] not in investigated:
        return False
    excerpt = fact.get("evidence_excerpt")
    return (isinstance(excerpt, str)
            and bool(re.search(r"\b" + re.escape(expected) + r"\b", excerpt, re.I)))


def _admission_deadline_supported(excerpt: Any, deadline: date) -> bool:
    """Use the same date-role proof as independent scholarship submissions."""
    return explicit_official_deadline(excerpt, deadline)


def admission_delivery_key(row: dict[str, Any]) -> str:
    """Original country/institution receipt hash, stable across URL revisions."""
    country = row["country_code"]
    institution = row["institution"].strip().casefold()
    return hashlib.sha256(f"{country}|{institution}".encode()).hexdigest()[:32]


def eligible_official_admissions_rows(
    catalog: Any, *, now: datetime,
) -> list[dict[str, Any]]:
    """Verify one programme per actual delivery identity; hold contradictions."""
    if (now.tzinfo is None or not isinstance(catalog, dict)
            or catalog.get("kind") != "economics_phd_admissions_observations"
            or catalog.get("scope") != "official_programme_sources_only"
            or not isinstance(catalog.get("source"), dict)
            or catalog["source"].get("deadline_values_reused") is not False):
        return []
    rows = catalog.get("programmes")
    if not isinstance(rows, list) or len(rows) > 500:
        return []
    now = now.astimezone(UTC)
    qualified: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("status") != "verified":
            continue
        raw_deadline = row.get("deadline_iso")
        if not isinstance(raw_deadline, str) or not ISO_DAY.fullmatch(raw_deadline):
            continue
        try:
            deadline = date.fromisoformat(raw_deadline)
        except ValueError:
            continue
        if not now.date() <= deadline <= (now + timedelta(days=366)).date():
            continue
        checked = _checked_utc(row.get("checked_at"))
        if checked is None or checked > now or now - checked > timedelta(days=14):
            continue
        host = admissions_host(row.get("official_programme_url"))
        if (host is None or admissions_host(row.get("evidence_url")) != host
                or not _independently_non_us(row, host)):
            continue
        institution = row.get("institution")
        if (not isinstance(institution, str) or not institution.strip()
                or not _admission_deadline_supported(
                    row.get("evidence_excerpt"), deadline,
                )):
            continue
        key = admission_delivery_key(row)
        if key in conflicts:
            continue
        previous = qualified.get(key)
        if previous is not None and any(
            previous.get(field) != row.get(field)
            for field in ("institution", "country_code", "official_programme_url",
                          "evidence_url", "deadline_iso")
        ):
            conflicts.add(key)
            qualified.pop(key, None)
            continue
        qualified[key] = row
    return sorted(qualified.values(), key=lambda row: (
        row["deadline_iso"], row["institution"].casefold(),
    ))
