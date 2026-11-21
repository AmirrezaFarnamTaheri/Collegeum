"""Shared fail-closed robots.txt body validator for official-source fetchers.

HTTP 200 is not sufficient proof of robots permission: a login/captcha/403
interstitial often comes back as a successful HTML page. A valid plain-text
User-agent rule must be present before a Python RobotFileParser is trusted.
HTTP 404 remains the caller's separately handled no-robots-file case.
"""
from __future__ import annotations

import re
import urllib.robotparser

MAX_POLICY_BYTES = 256 * 1024
_USER_AGENT = re.compile(r"(?mi)^[ \t]*user-agent[ \t]*:[ \t]*\S+[ \t]*$")
_BAD_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def parse_official_robots(
    body: bytes, parser: urllib.robotparser.RobotFileParser,
) -> None:
    """Parse a real, bounded UTF-8 robots file, rejecting challenge responses."""
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_POLICY_BYTES:
        raise ValueError("robots_unavailable")
    try:
        text = body.decode("utf-8-sig", errors="strict")
    except UnicodeError as exc:
        raise ValueError("robots_unavailable") from exc
    if not text.strip() or _BAD_CONTROLS.search(text):
        raise ValueError("robots_unavailable")
    # A login/interstitial must not silently become an empty allow-all rule.
    if text.lstrip().startswith(("<", "{", "[")) or not _USER_AGENT.search(text):
        raise ValueError("robots_unavailable")
    # Disallow arbitrary excessively long policy lines; the crawler only
    # needs the normal syntactically valid directives in a bounded text file.
    if any(len(line) > 8192 for line in text.splitlines()):
        raise ValueError("robots_unavailable")
    parser.parse(text.splitlines())
