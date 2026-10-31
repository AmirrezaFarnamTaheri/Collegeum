"""Reviewed Bern employer-advert identity and non-destructive display corrections.

Only validated jobs.unibe.ch vacancy URLs can refer to these exact UUIDs.
The source journal, stable key, first-seen timestamps and Telegram receipts
are immutable; sanitize copies exclusively for downstream presentation.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

_OFFICIAL_PATH = re.compile(
    r"/(?:job-vacancies|offene-stellen)/[a-z0-9-]+/"
    r"(?P<viewkey>[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})/?\Z",
    re.I,
)
# Employer-verified requirements: physics/engineering (not a life-sciences MSc).
_REVIEWED_OTHER_FIELDS = frozenset({
    "a5825edd-e430-405e-a30e-935d10b872db",  # NCCR Genesis optical remote sensing
    "63cc79b4-88b8-4d0b-b4df-67ad952ed3de",  # Multisensory Development
})
# Historical API-index dates published before employer-specific verification.
_REVIEWED_UNVERIFIED_ENDS = {
    "0a6853ac-d531-4ac1-bc57-592090585e19": (
        "2026-11-27", "Unverified index end date; employer advert states no cutoff",
    ),
    "7e52c2be-b908-4dfd-b634-c72519d07262": (
        "2026-12-31", "Rolling until filled; not a confirmed hard deadline",
    ),
}


def bern_vacancy_viewkey(url: str) -> str | None:
    """Identify an official employer listing, never a third-party copied UUID."""
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "jobs.unibe.ch"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.query or parsed.fragment
        ):
            return None
        match = _OFFICIAL_PATH.fullmatch(parsed.path)
    except ValueError:
        return None
    return match.group("viewkey").lower() if match else None


def reviewed_non_life_vacancy(url: str) -> bool:
    """Only these two employer-reviewed, engineering-led roles are excluded."""
    return bern_vacancy_viewkey(url) in _REVIEWED_OTHER_FIELDS


def sanitize_bern_historical_deadline(job: dict[str, Any]) -> dict[str, Any]:
    """Redact an *exact known* false index cutoff in a display copy only.

    A later employer-confirmed replacement, different source, different date
    or independently-authored note is retained unchanged.
    """
    view = dict(job)
    if job.get("source") != "life_dach_bern":
        return view
    viewkey = bern_vacancy_viewkey(str(job.get("url") or ""))
    verified = _REVIEWED_UNVERIFIED_ENDS.get(viewkey or "")
    if (
        verified is not None
        and str(job.get("deadline") or "") == verified[0]
        and str(job.get("deadline_note") or "").startswith(
            "Official UniBE posting ends"
        )
    ):
        view["deadline"] = ""
        view["deadline_note"] = verified[1]
    return view
