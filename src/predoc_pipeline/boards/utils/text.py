"""Text normalisation, hashing and URL canonicalisation helpers."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from ...core.identity import INSTITUTION_ALIASES as INSTITUTION_ALIASES
from ...core.identity import normalize_institution as normalize_institution
from ...core.urls import TRACKING_PARAMS as TRACKING_PARAMS
from ...core.urls import canonicalize_url

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
# Gender / boilerplate suffixes common on European boards: (m/f/d), (w/m/d), (f/m/x) ...
_GENDER_TAG = re.compile(r"\((?:[mwfdx]\s*/\s*){1,3}[mwfdx]\)", re.IGNORECASE)
_LINKEDIN_JOB_ID_RX = re.compile(r"/jobs/view/(?:[^/?#]*-)?(\d{6,})(?:/|$)")


def clean_ws(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return _WS.sub(" ", text).strip()


def normalize_title(title: str) -> str:
    t = clean_ws(title).lower()
    t = _GENDER_TAG.sub(" ", t)
    t = t.replace("pre-doctoral", "predoctoral").replace("pre doctoral", "predoctoral")
    t = t.replace("pre-doc", "predoc").replace("pre doc", "predoc")
    t = _PUNCT.sub(" ", t)
    return _WS.sub(" ", t).strip()



def canonical_url(url: str) -> str:
    """Normalise posting URLs while retaining functional IDs and clickable hosts."""
    url = clean_ws(url)
    if not url:
        return url
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path
    # LinkedIn: /jobs/view/<slug>-<id> -> /jobs/view/<id>
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        m = _LINKEDIN_JOB_ID_RX.search(path)
        if m:
            return f"https://www.linkedin.com/jobs/view/{m.group(1)}"
    return canonicalize_url(url, preserve_www=True)


def absolutize(base: str, href: str) -> str:
    return urljoin(base, href.strip())


def sha256(*parts: str) -> str:
    h = hashlib.sha256()
    h.update("|".join(parts).encode("utf-8"))
    return h.hexdigest()


def html_to_text(html: str, max_chars: int | None = None) -> str:
    """Extract readable text from an HTML page, dropping nav/script/style chrome."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text(" ", strip=True)
    text = clean_ws(text)
    return text[:max_chars] if max_chars else text


def truncate(text: str, n: int) -> str:
    text = clean_ws(text)
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


_ROLE_AT = re.compile(r"^(?P<role>.+?)\s+(?:at|@)\s+(?P<inst>.+?)(?:\s*\((?P<loc>[^()]+)\))?\s*$", re.IGNORECASE)


def split_role_at_institution(title: str) -> tuple[str, str | None, str | None]:
    """'Predoc RA in Dev Econ at LSE (UK)' -> ('Predoc RA in Dev Econ', 'LSE', 'UK')."""
    m = _ROLE_AT.match(clean_ws(title))
    if not m:
        return clean_ws(title), None, None
    return m.group("role").strip(), m.group("inst").strip(), (m.group("loc") or None)
