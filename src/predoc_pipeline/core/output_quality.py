"""Conservative validation of vacancy links and scraped authentication pages.

The signals below establish that a *link* is unsuitable for direct job
application; they do NOT establish whether the opportunity itself is filled.
Keep a flagged record in history, but do not present it as an actionable job.
This module is stdlib-only and used by ingest, exports, and offline audits.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlsplit

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
# Verified employer-specific exception: this EPIC page explains the
# fellowship programme but is not a vacancy-specific application.
# Do not reject all `/about/` paths: many official jobs use them.
_NON_ACTIONABLE_PROGRAM_PAGES = frozenset({
    ("epic.uchicago.edu",
     "/about/jobs-fellowships/fellowships/predoctoral-fellows/"
     "predoctoral-fellowship-program/about"),
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
    if (hostname, decoded.rstrip("/")) in _NON_ACTIONABLE_PROGRAM_PAGES:
        return "generic-program-information-page"
    if hostname == "job-boards.greenhouse.io" and "true" in (
        value.lower() for value in parse_qs(parts.query).get("error", [])
    ):
        return "error-page-url"
    if hostname in _AUTH_HOSTS and (
        hostname != "accounts.google.com" or
        re.search(r"(?i)/(?:v\d+/)?(?:signin|oauth|account|servicelogin)", decoded)
    ):
        return "authentication-redirect"
    if hostname in _GENERIC_ROOTS and decoded in ("", "/") and not parts.query:
        return "generic-job-board-homepage"
    # The EURAXESS search route contains multiple vacancies and no
    # position-specific application identity. Keep individual /jobs/<ID> links.
    if hostname in {"euraxess.ec.europa.eu", "www.euraxess.ec.europa.eu"} and (
        decoded.rstrip("/").casefold() == "/jobs/search"
    ):
        return "generic-job-board-search"
    return None


# Source-evidence-reviewed, out-of-scope historical vacancies. Never infer
# a vacancy closed from a subject mismatch. Preserve the durable journal and
# any delivery receipts; prevent re-publication in web, RSS and subscriptions.
# Hashes are stable URL identities and are reviewed individually (not inferred
# from title similarity or project affiliation).
_REVIEWED_WRONG_FIELD_URL_HASHES = frozenset({
    # SIEPR current staff/postdoc directory, not a vacancy index.
    "3c0f5a1439671f2e2848d26aa519ac9a588e850b35dec70b7cc7dc85824f64a6",
    # SIEPR directory of current predoctoral fellows, not open requisitions.
    "c838a6d783151ffaa97aa1942caeeddee0a39d9554c3aea0dc19afc4c09d3ec7",
    # Stanford-only Undergraduate Research Fellows, not a post-baccalaureate job.
    "33eb1b1a810a3a66249a92008daab32a9b67b678f77d48e36db17c6761a932be",
    # Gothenburg PAR 2026/834: doctoral Social Work / crime prevention, not economics.
    "07c9e135ca70ad498084d2521ac6fcf1c1fd54deefd52a702e696fa13f8278ef",
    # University of Chicago Freedman Lab neuroscience, not economics.
    "b35dfeb8c8a0c10d4d2c9f95a273b4e8a614087f943840bdc8dcbb20444cdc5f",
    # University of Copenhagen: pure mathematics postdoc (listing ID 170).
    # Distinct from its mathematics of insurance and economics postdoc.
    "d702a7eee570446b9e41c7493d7403550bbbd7a4b25e9dc20297b398f0ba24cd",
    # Cambridge McDonald Institute: digital archaeological-site documentation
    # research assistant (listing ID 259; prior Telegram receipt retained).
    "60d312d334ece3e229027c162db2d87e991933e97639467b3688b0e19065aa59",
})


def excluded_by_audit(url_hash: object) -> bool:
    """Apply explicit, source-evidenced field exclusions by durable URL key."""
    return isinstance(url_hash, str) and url_hash in _REVIEWED_WRONG_FIELD_URL_HASHES


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
