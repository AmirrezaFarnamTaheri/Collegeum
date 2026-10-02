"""Deterministic URL canonicalisation and identity hashing. Stdlib only.

Two listings are the *same* listing when their application URLs canonicalise to
the same string, so this module underpins both Tier 1 deduplication and the
pre-extraction "have I already judged this?" gate. It must behave identically
across runs, machines and library versions, which is why it does not delegate
to w3lib.

Canonical form:
  * scheme and host lowercased, default ports dropped
  * a ``www.`` prefix dropped when a real subdomain remains
  * fragment dropped
  * tracking and session parameters dropped (see TRACKING_PARAMS)
  * remaining query parameters sorted by (key, value)
  * percent-encoding normalised; unreserved characters decoded
  * trailing slash dropped from non-root paths
  * IDN hosts normalised to punycode

Path case is preserved: many applicant-tracking systems route on case-sensitive
identifiers, and folding them merges distinct vacancies.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, quote, unquote, urlsplit, urlunsplit

__all__ = [
    "TRACKING_PARAMS",
    "canonicalize_url",
    "url_hash",
    "content_hash",
    "composite_key",
    "registrable_host",
]

TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        # analytics
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "utm_id", "utm_name", "utm_reader", "utm_social", "utm_brand",
        # ad networks and social
        "fbclid", "gclid", "gclsrc", "dclid", "msclkid", "twclid", "igshid",
        "yclid", "wbraid", "gbraid", "ttclid", "li_fat_id",
        # newsletter and CRM
        "mc_cid", "mc_eid", "mkt_tok", "_hsenc", "_hsmi", "hsctatracking",
        "vero_id", "vero_conv", "ck_subscriber_id",
        # job boards
        "refid", "ref", "referer", "referrer", "trackingid", "trk",
        "trkcampaign", "trackid", "src", "source", "originalsubdomain",
        "recommendedflavour", "eboid", "sponsored", "campaignid",
        "jobsearchtype", "savedsearchid",
        # sessions
        "sessionid", "sid", "phpsessid", "jsessionid", "aspsessionid",
        "_ga", "_gl", "cmpid", "cid",
    }
)

_DEFAULT_PORTS = {"http": "80", "https": "443"}
_UNRESERVED_SAFE = "-._~"


def _normalise_pct(value: str, safe: str) -> str:
    """Decode unreserved escapes, then re-encode to one canonical spelling."""
    return quote(unquote(value), safe=safe + _UNRESERVED_SAFE)


def _normalise_host(host: str) -> str:
    host = host.strip().rstrip(".").lower()
    if not host:
        return ""
    try:
        host = host.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError):
        pass  # a malformed host is data to record, not a reason to raise
    if host.startswith("www.") and host.count(".") >= 2:
        host = host[4:]
    return host


def canonicalize_url(url: str, *, drop_tracking: bool = True) -> str:
    """Return a stable canonical spelling of ``url``.

    Unparseable input is returned stripped rather than raising.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw and not raw.startswith("//"):
        raw = "https://" + raw.lstrip("/")

    try:
        parts = urlsplit(raw)
        host_raw = parts.hostname or ""
        port = parts.port
    except ValueError:
        return raw

    scheme = (parts.scheme or "https").lower()
    host = _normalise_host(host_raw)
    if port is not None and str(port) == _DEFAULT_PORTS.get(scheme, ""):
        port = None

    netloc = host
    if parts.username:
        credentials = parts.username
        if parts.password:
            credentials += f":{parts.password}"
        netloc = f"{credentials}@{netloc}"
    if port is not None:
        netloc = f"{netloc}:{port}"

    path = _normalise_pct(parts.path or "/", safe="/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"

    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if drop_tracking:
        pairs = [(k, v) for k, v in pairs if k.lower() not in TRACKING_PARAMS]
    pairs.sort(key=lambda kv: (kv[0], kv[1]))
    query = "&".join(
        f"{_normalise_pct(k, safe='')}={_normalise_pct(v, safe='')}" for k, v in pairs
    )

    return urlunsplit((scheme, netloc, path, query, ""))


def clean_url(url: str) -> str:
    """A link safe to show and click: trimmed, with a scheme, without the #fragment.

    ``canonicalize_url`` is for *identity* (hashing, dedupe). It drops "www.",
    trailing slashes and percent-encodes reserved characters -- fine for a
    hash, but it can break the actual link: ``cemfi.es`` without "www." may not
    resolve, and Varbi's ``/what:job/jobID:123`` path 404s as ``what%3Ajob``.
    Links shown to people therefore keep their original spelling.
    """
    raw = (url or "").strip()
    if not raw or raw.lower().startswith(("mailto:", "tel:", "javascript:", "data:")):
        return ""
    if "://" not in raw and not raw.startswith("//"):
        raw = "https://" + raw.lstrip("/")
    elif raw.startswith("//"):
        raw = "https:" + raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return ""
    # Encode only what is invalid in a URL (spaces, non-ASCII); reserved
    # characters and existing %XX escapes are left exactly as they were.
    path = quote(parts.path or "/", safe="/:@!$&'()*+,;=%~-._")
    query = quote(parts.query, safe="=&%/:?@!$'()*+,;~-._")
    return urlunsplit((parts.scheme.lower(), parts.netloc, path, query, ""))


def url_hash(url: str) -> str:
    """SHA-256 of the canonical URL. The stable identity key for a listing."""
    return hashlib.sha256(canonicalize_url(url).encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    """SHA-256 of whitespace-normalised text. Detects unchanged re-fetches."""
    normalised = " ".join((text or "").split()).lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def registrable_host(url: str) -> str:
    """Host of the canonical URL, or '' when there isn't one."""
    try:
        return urlsplit(canonicalize_url(url)).hostname or ""
    except ValueError:
        return ""


_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)


def composite_key(
    institution: str, title: str, principal_investigator: str | None = None
) -> str:
    """Normalised join used by the fuzzy deduplication tier.

    Punctuation is stripped so "Prof. Ada Lovelace" and "Prof Ada Lovelace"
    collapse before the edit-distance comparison rather than costing two points
    of similarity for a full stop.
    """
    parts = (institution or "", title or "", principal_investigator or "")
    cleaned = (" ".join(_PUNCT.sub(" ", p).lower().split()) for p in parts)
    return " | ".join(cleaned)
