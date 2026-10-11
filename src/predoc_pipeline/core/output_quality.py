"""Conservative validation of vacancy links and scraped authentication pages.

The signals below establish that a *link* is unsuitable for direct job
application; they do NOT establish whether the opportunity itself is filled.
Keep a flagged record in history, but do not present it as an actionable job.
This module is stdlib-only and used by ingest, exports, and offline audits.
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

_TEMPLATE = re.compile(
    r"(?i)(?:\[(?:nid|job_?id|vacancy_?id|id)\]|"
    r"\{(?:nid|job_?id|vacancy_?id|id)\}|"
    r"<(?:nid|job_?id|vacancy_?id|id)>|"
    r"(?<!\w)(?:undefined|null)(?!\w))"
)
_GENERIC_ROOTS = frozenset({
    "econjobmarket.org", "www.econjobmarket.org",
    "jobs.ac.uk", "www.jobs.ac.uk",
    "linkedin.com", "www.linkedin.com",
    "academictransfer.com", "www.academictransfer.com",
    "jobicy.com", "www.jobicy.com",
})
_AUTH_HOSTS = frozenset({
    "accounts.google.com", "login.microsoftonline.com",
    "login.live.com", "appleid.apple.com",
})


def application_url_issue(url: object) -> str | None:
    """Return a stable issue code only for objectively non-actionable URLs.

    Do not unconditionally reject HTTP: some university job portals still
    expose legitimate position-specific URLs. HTTP is a security advisory,
    not proof that the job is fake or closed.
    """
    if not isinstance(url, str) or not url.strip() or len(url) > 4096:
        return "invalid-url"
    try:
        parts = urlsplit(url.strip())
        hostname = (parts.hostname or "").lower()
        _ = parts.port
    except ValueError:
        return "invalid-url"
    if parts.scheme.lower() not in ("http", "https") or not hostname:
        return "invalid-url"
    decoded = unquote(parts.path)
    if _TEMPLATE.search(decoded):
        return "unresolved-url-template"
    if hostname in _AUTH_HOSTS and (
        hostname != "accounts.google.com" or
        re.search(r"(?i)/(?:v\d+/)?(?:signin|oauth|account|servicelogin)", decoded)
    ):
        return "authentication-redirect"
    if hostname in _GENERIC_ROOTS and decoded in ("", "/") and not parts.query:
        return "generic-job-board-homepage"
    return None


def authentication_page_text(text: object) -> bool:
    """Recognize login boilerplate only when multiple independent cues occur."""
    if not isinstance(text, str):
        return False
    lowered = " ".join(text.lower().split())[:3000]
    signals = (
        "sign in to continue", "email or phone", "forgot email",
        "not your computer", "create account",
        "verify you're human", "authentication required",
    )
    return sum(token in lowered for token in signals) >= 2
