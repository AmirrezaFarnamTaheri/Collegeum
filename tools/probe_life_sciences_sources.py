"""Bounded, read-only audit of the opt-in Life Sciences PhD source registry.

This checks only explicitly enabled public landing pages; it never accesses
subscriber state. A 200 response with zero recognized vacancy links is NOT
evidence that the scraper still works. Fetches honor the existing polite
client's robots.txt checks and per-host pacing.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.ingest.http import PoliteClient
from predoc_pipeline.ingest.life_sciences import load_life_sources

MAX_PROBE_SOURCES = 16
MAX_PARSE_CHARS = 650_000
MAX_QUERY_URLS = 4  # maximum number of configured URLs per enabled source
REGIONS = frozenset((
    "all", "core", "nordics", "dach", "benelux", "france_iberia",
    "central_south", "aggregator_topics", "eastern_balkans",
    "specialist_institutes", "doctoral_programmes",
))
PROBE_USER_AGENT = (
    "Collegeum-LSSourceProbe/1.0 "
    "(+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
)


def candidate_job_urls(content: str, url: str, pattern: str) -> set[str]:
    """Recognize unique public HTTPS vacancy anchors, not script-only substrings."""
    soup = BeautifulSoup(content[:MAX_PARSE_CHARS], "lxml")
    matcher = re.compile(pattern, re.I)
    found: set[str] = set()
    for anchor in soup.select("a[href]")[:4000]:
        link = urljoin(url, str(anchor.get("href") or ""))
        try:
            parts = urlsplit(link)
        except ValueError:
            continue
        if (
            parts.scheme == "https" and parts.hostname
            and not parts.username and not parts.password
            and matcher.search(link)
        ):
            found.add(link)
    return found


def candidate_links(content: str, url: str, pattern: str) -> int:
    """Retain the count API used by existing fixtures and health checks."""
    return len(candidate_job_urls(content, url, pattern))

def feed_entries(content: str) -> int:
    """Count actual RSS/Atom entries, ignoring metadata and shell pages."""
    import feedparser

    result = feedparser.parse(content[:MAX_PARSE_CHARS])
    return len(result.entries)


def check_sources(
    client: Any, config: str | Path, *, region: str = "all",
    limit: int = MAX_PROBE_SOURCES, offset: int = 0,
) -> dict[str, Any]:
    """Produce public counts without downloading individual vacancy details."""
    if not 1 <= limit <= MAX_PROBE_SOURCES:
        raise ValueError("limit must be between 1 and 16")
    if not 0 <= offset <= 256:
        raise ValueError("offset must be between 0 and 256")
    if region not in REGIONS:
        raise ValueError("unknown source region")
    sources = [s for s in load_life_sources(config) if s.enabled]
    if region == "core":
        core_ids = {
            s.name for s in load_board_sources(config) if s.enabled
        }
        sources = [s for s in sources if s.name in core_ids]
    elif region != "all":
        config_file = Path(config).parent / "life_sciences_sources" / f"{region}.toml"
        regional_ids = {s.name for s in load_board_sources(config_file)}
        sources = [s for s in sources if s.name in regional_ids]

    report: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "region": region,
        "enabled_in_scope": len(sources),
        "offset": offset, "limit": limit,
        "next_offset": (
            min(offset + limit, len(sources))
            if offset + limit < len(sources) else None
        ),
        "checked": 0,
        "sources": {},
    }
    for source in sources[offset:offset + limit]:
        urls = source.opt("urls") or (
            [source.opt("url")] if source.opt("url") else []
        )
        # One source may expose multiple subject-search URLs. Checking only
        # urls[0] both misses vacancies and conceals failures on later pages.
        if not urls:
            report["sources"][source.name] = {
                "status": "missing_url", "http_status": 0, "vacancy_links": 0,
                "urls_total": 0, "urls_checked": 0, "endpoints": [],
            }
            report["checked"] += 1
            continue
        if len(urls) > MAX_QUERY_URLS:
            # Do not silently scan only a subset or make unbounded requests.
            report["sources"][source.name] = {
                "status": "too_many_urls", "http_status": 0, "vacancy_links": 0,
                "urls_total": len(urls), "urls_checked": 0, "endpoints": [],
            }
            report["checked"] += 1
            continue

        endpoints: list[dict[str, Any]] = []
        vacancy_urls: set[str] = set()
        rss_entry_count = 0
        for url in urls:
            try:
                response = client.get(url, use_cache=False)
            except Exception as exc:  # noqa: BLE001 - keep other query pages observable
                endpoints.append({
                    "url": url, "status": "http_error", "http_status": 0,
                    "vacancy_links": 0, "failure_type": type(exc).__name__,
                })
                continue
            status = (
                "blocked_robots" if response.status == 999 else
                "http_error" if not response.ok else "ok"
            )
            matched = 0
            if response.ok:
                if source.type == "rss":
                    matched = feed_entries(response.text)
                    rss_entry_count += matched
                elif source.type == "link_scan":
                    try:
                        links = candidate_job_urls(
                            response.text, url, source.opt("link_pattern", "^$"),
                        )
                        matched = len(links)
                        vacancy_urls.update(links)
                    except re.error:
                        status = "invalid_pattern"
                else:
                    status = "unsupported_scraper"
                if status == "ok" and matched == 0:
                    status = "no_recognized_vacancy_links"
            endpoints.append({
                "url": url, "status": status, "http_status": response.status,
                "vacancy_links": matched,
            })

        states = [item["status"] for item in endpoints]
        problems = {"blocked_robots", "http_error", "invalid_pattern", "unsupported_scraper"}
        if "ok" in states:
            status = "partial" if any(s in problems for s in states) else "ok"
        elif all(s == "no_recognized_vacancy_links" for s in states):
            status = "no_recognized_vacancy_links"
        elif all(s == states[0] for s in states):
            status = states[0]
        else:
            status = "partial"

        report["sources"][source.name] = {
            "status": status,
            "http_status": endpoints[0]["http_status"],  # compatibility
            "vacancy_links": (
                len(vacancy_urls) if source.type == "link_scan"
                else rss_entry_count
            ),
            "urls_total": len(urls), "urls_checked": len(endpoints),
            "endpoints": endpoints,
        }
        report["checked"] += 1
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/life_sciences.toml")
    parser.add_argument("--region", default="all", choices=sorted(REGIONS))
    parser.add_argument("--limit", type=int, default=MAX_PROBE_SOURCES)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--output", type=Path, default=Path("build/life-sciences-sources.json"),
    )
    args = parser.parse_args()
    with PoliteClient(
        user_agent=PROBE_USER_AGENT,
        timeout=15.0, per_host_delay=3.0, respect_robots=True,
    ) as client:
        report = check_sources(
            client, args.config, region=args.region, limit=args.limit,
            offset=args.offset,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
