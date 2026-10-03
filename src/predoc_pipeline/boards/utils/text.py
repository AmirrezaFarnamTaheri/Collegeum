"""Text normalisation, hashing and URL canonicalisation helpers."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
# Gender / boilerplate suffixes common on European boards: (m/f/d), (w/m/d), (f/m/x) ...
_GENDER_TAG = re.compile(r"\((?:[mwfdx]\s*/\s*){1,3}[mwfdx]\)", re.IGNORECASE)
_LINKEDIN_JOB_ID_RX = re.compile(r"(\d{6,})")

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "refid", "trk", "trackingid",
    "position", "pagenum", "src", "source", "sessionid",
}

INSTITUTION_ALIASES = {
    "lse": "london school of economics and political science",
    "london school of economics": "london school of economics and political science",
    "ucl": "university college london",
    "lbs": "london business school",
    "sse": "stockholm school of economics",
    "ucph": "university of copenhagen",
    "ku": "university of copenhagen",
    "upf": "universitat pompeu fabra",
    "bse": "barcelona school of economics",
    "ubc": "university of british columbia",
    "uoft": "university of toronto",
    "u of t": "university of toronto",
    "eui": "european university institute",
    "tse": "toulouse school of economics",
    "pse": "paris school of economics",
    "ifs": "institute for fiscal studies",
    "ecb": "european central bank",
}

_STOP = {"the", "of", "and", "for", "in", "at", "a", "an", "de", "la", "le", "du"}


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


def normalize_institution(name: str | None) -> str:
    n = clean_ws(name).lower()
    n = INSTITUTION_ALIASES.get(n, n)
    n = _PUNCT.sub(" ", n)
    words = [w for w in n.split() if w not in _STOP]
    return " ".join(words)


def canonical_url(url: str) -> str:
    """Strip fragments/tracking params so the same posting hashes identically."""
    url = clean_ws(url)
    if not url:
        return url
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in TRACKING_PARAMS]
    host = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    # LinkedIn: /jobs/view/<slug>-<id> -> /jobs/view/<id>
    if "linkedin.com" in host:
        m = _LINKEDIN_JOB_ID_RX.search(path)
        if m and "/jobs/view" in path:
            return f"https://www.linkedin.com/jobs/view/{m.group(1)}"
    return urlunsplit((parts.scheme.lower() or "https", host, path, urlencode(query), ""))


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
