"""Read-only, robots-checked UZH Economics source proof for GitHub runners.

This module never sends Telegram messages, changes source settings, persists
vacancies, or treats an empty department page as verified source coverage.
The CLI logs only aggregate counts and sanitized transport status.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from predoc_pipeline.boards.collector import build_http
from predoc_pipeline.boards.config import HttpConfig, SourceConfig, load_board_sources
from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper
from predoc_pipeline.ingest.http import PoliteClient

INDEX = "https://www.econ.uzh.ch/en/about/jobs.html"
MAX_HTML_CHARS = 1_000_000
DOCTORAL_TITLE = re.compile(r"\b(?:ph\.?d\.?|pre[- ]?doc(?:toral)?|doctoral)\b", re.I)


class _NoNetwork:
    """The HTML classifier must never initiate a detail page fetch."""

    def set_host_interval(self, *_args: object) -> None:
        pass


def inspect_html(cfg: SourceConfig, html: str) -> dict[str, object]:
    """Return fixed-shape aggregate index evidence; no raw ads or URLs."""
    if cfg.name != "uzh" or cfg.opt("url") != INDEX or cfg.type != "link_scan":
        raise ValueError("Unexpected UZH configuration")
    if not isinstance(html, str) or len(html) > MAX_HTML_CHARS:
        return {
            "source_state": "unverified-oversize",
            "official_employer_links": 0, "parsed_vacancies": 0,
            "doctoral_title_signals": 0, "parser_errors": 1,
            "verified_empty": False,
        }
    soup = BeautifulSoup(html, "lxml")
    pattern = re.compile(str(cfg.opt("link_pattern")), re.I)
    official: set[str] = set()
    host_links: set[str] = set()
    anchors = soup.select("a[href]")
    for anchor in anchors:
        absolute = urljoin(INDEX, str(anchor.get("href") or ""))
        try:
            parts = urlsplit(absolute)
            valid_host = (
                parts.scheme == "https"
                and parts.hostname == "jobs.uzh.ch"
                and parts.username is None and parts.password is None
                and parts.port in (None, 443)
                and not any(c.isspace() or c == "\\" for c in absolute)
            )
        except ValueError:
            valid_host = False
        if valid_host:
            host_links.add(absolute)
            if pattern.search(absolute):
                official.add(absolute)
    parser = LinkScanScraper(cfg, _NoNetwork())
    parsed = parser.parse_postings([(INDEX, html)])
    error_count = len(parser.discovery_parse_errors)
    state = (
        "degraded-parser" if error_count else
        "vacancy-links-observed" if parsed else
        "unverified-empty"
    )
    return {
        "source_state": state,
        "html_characters": len(html),
        "total_href_anchors": len(anchors),
        "jobs_host_anchors": len(host_links),
        "has_open_positions_heading": any(
            "open positions" in heading.get_text(" ", strip=True).casefold()
            for heading in soup.select("h1,h2,h3,h4")
        ),
        "official_employer_links": len(official),
        "parsed_vacancies": len(parsed),
        "doctoral_title_signals": sum(
            bool(DOCTORAL_TITLE.search(item.title)) for item in parsed
        ),
        "parser_errors": error_count,
        "verified_empty": False,
    }


async def run() -> int:
    cfg = next(
        item for item in load_board_sources(Path("config/sources.toml"))
        if item.name == "uzh"
    )
    # The production async adapter does not independently consult robots.
    # Verify the exact official target with the fail-closed policy client
    # before ONE read-only fetch using production's async HTTP implementation.
    with PoliteClient(
        user_agent=(
            "Collegeum-UZH-SourceProbe/1.0 "
            "(+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
        ),
        timeout=12, per_host_delay=3, respect_robots=True,
    ) as policy:
        if not policy.allowed(INDEX):
            print(json.dumps({"source_state": "robots-denied-or-unverified"}))
            return 2
    http_cfg = HttpConfig(
        timeout=18, max_retries=0, backoff_base=1,
        default_min_interval=3, max_concurrent_sources=1,
        source_timeout=30,
    )
    async with build_http(http_cfg) as client:
        try:
            html = await client.get_text(INDEX, stop_on_429=True)
        except Exception as exc:  # noqa: BLE001 - sanitize provider errors
            status = getattr(exc, "status", None)
            print(json.dumps({
                "source_state": "fetch-unverified",
                "http_status": status if type(status) is int else None,
                "error_type": type(exc).__name__,
            }))
            return 2
    result = inspect_html(cfg, html)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["source_state"] == "vacancy-links-observed" else 2


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
