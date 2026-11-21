"""Bounded, fail-closed HTML integrity checks shared by official monitors.

HTTP 200 does not establish that a university served the requested page.
Challenges can contain plausible dates, so validate the *entire* bounded
response before extracting scholarship or general PhD admission evidence.
Only recognize explicit access-gate signatures, not ordinary login links.
"""
from __future__ import annotations

import re
from typing import Any

MAX_OFFICIAL_HTML_BYTES = 1024 * 1024

_ACCESS_GATE = re.compile(
    r"<(?:title|h1)\b[^>]*>\s*(?:just a moment|access denied|"
    r"403(?: forbidden)?|login required|sign in required|"
    r"service unavailable|bot verification|captcha verification)\b",
    re.I,
)
_CHALLENGE_CONTROL = re.compile(
    r"\b(?:cf_chl|cf-chl|challenge-form|g-recaptcha|h-captcha)\b",
    re.I,
)


def official_html_response_problem(
    body: Any, *, max_bytes: int = MAX_OFFICIAL_HTML_BYTES,
) -> str | None:
    """Return an integrity failure reason, or None for usable source HTML.

    This does not establish scholarship eligibility or site authenticity;
    it only keeps failed access checks from being recorded as successful
    reviews. Callers must still check HTTPS, robots and final URL.
    """
    if (not isinstance(body, str) or not body.strip().startswith("<")
            or len(body.encode("utf-8")) > max_bytes):
        return "invalid_html"
    if _ACCESS_GATE.search(body) or _CHALLENGE_CONTROL.search(body):
        return "access_interstitial"
    return None
