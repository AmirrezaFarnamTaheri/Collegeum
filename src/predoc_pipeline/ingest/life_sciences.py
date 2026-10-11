"""Independent, opt-in European life-sciences doctoral discovery.

Uses the existing bounded board adapters without the economics relevance
filter. The public career journal is shared, but this category is only
matched for subscribers who select life_sciences_phd. A job must have
doctoral-role evidence, life-science content and a known European country.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..boards.collector import build_http
from ..boards.config import HttpConfig, load_board_sources
from ..boards.filter import PHD_POSITION
from ..boards.models import JobPostSchema
from ..boards.scrapers import SCRAPERS
from ..boards.utils.geo import detect_location
from .career import load_career, save_career

CATEGORY = "life_sciences_phd"
MAX_SOURCES = 8
MAX_PER_SOURCE = 60
MAX_TOTAL = 200

# Primary research interests and nearby areas are separate so the alert can
# communicate why a posting matched without pretending to verify funding.
PRIMARY_FIELD = re.compile(
    r"\b(?:epigenetic\w*|epiallel\w*|chromatin|histone\w*|"
    r"regulatory genom\w*|functional genom\w*|gene regulat\w*|"
    r"transcriptional regulat\w*|neurodevelop\w*|"
    r"psychiatric genetic\w*|psychiatric genomic\w*|"
    r"dna methylat\w*)\b", re.I,
)
RELATED_FIELD = re.compile(
    r"\b(?:molecular biolog\w*|cell(?:ular)? biolog\w*|"
    r"developmental biolog\w*|genom\w*|genetic\w*|"
    r"bioinformatic\w*|computational biolog\w*|systems biolog\w*|"
    r"transcriptom\w*|proteom\w*|crispr|rna biolog\w*|"
    r"single[\s-]cell|stem[\s-]cell\w*|ipsc\w*|"
    r"organoid\w*|neuroscien\w*|neurobiolog\w*)\b", re.I,
)
UNFUNDED = re.compile(
    r"\b(?:self[\s-]funded|self[\s-]financed|unfunded|"
    r"no funding available|no stipend provided)\b", re.I,
)
WRONG_ROLE = re.compile(
    r"\bpost[\s-]?doc(?:toral)?\b|"
    r"\b(?:requires?|required)\s+(?:an?\s+)?(?:completed\s+)?ph\.?d\.?\b|"
    r"\bph\.?d\.?\s+(?:degree|qualification)\s+(?:required|essential)\b",
    re.I,
)
COUNTRY_EXCLUDE = frozenset(("Europe", "United Kingdom", "United States", "Canada"))
EXPLICIT_LOCATION = re.compile(
    r"\b(?:location|workplace|place of work|work location|based in)"
    r"\s*[:\-]\s*([^;\n.]{2,90})", re.I,
)


def classify_post(post: JobPostSchema, *, today: date | None = None) -> dict[str, str] | None:
    """Fail closed on unknown geography, broad roles and unfunded adverts."""
    if not PHD_POSITION.search(post.title) or WRONG_ROLE.search(post.title):
        return None
    context = " ".join(x for x in (
        post.title, post.department, post.fields_of_research,
        post.description_snippet,
    ) if x)
    primary = bool(PRIMARY_FIELD.search(context))
    if not primary and not RELATED_FIELD.search(context):
        return None
    if UNFUNDED.search(context):
        return None
    country, region = detect_location(post.country, post.location)
    if not country and not post.country and not post.location:
        # A broad European research organization can recruit internationally.
        # Only a labelled location in the vacancy itself is evidence of where
        # the position is based; collaborator addresses do not qualify.
        match = EXPLICIT_LOCATION.search(post.description_snippet)
        if match:
            country, region = detect_location(match.group(1))
    if region != "Europe" or not country or country in COUNTRY_EXCLUDE:
        return None
    current = today or datetime.now(UTC).date()
    if post.deadline and post.deadline < current:
        return None
    if post.date_posted and post.date_posted < current - timedelta(days=60):
        return None
    try:
        parsed = urlsplit(post.url)
        valid = parsed.scheme == "https" and bool(parsed.hostname)
        _ = parsed.port
    except ValueError:
        return None
    if not valid or len(post.url) > 1024 or not 5 <= len(post.title) <= 500:
        return None
    key = "career:" + hashlib.sha256(post.url.encode("utf-8")).hexdigest()[:32]
    return {
        "key": key, "category": CATEGORY, "scope": "",
        "title": post.title[:200],
        "employer": (post.institution or "Research institution")[:160],
        "location": (post.location or country)[:100],
        "source": post.source[:80], "url": post.url,
        "research_priority": "focus" if primary else "related",
        "funding_status": "unverified",
    }


async def discover(
    sources_path: str | Path, http_config: HttpConfig,
) -> tuple[list[JobPostSchema], list[str]]:
    """Query independently configured, bounded academic sources.

    One scraper failure is logged as a source error without stopping others.
    The adapters inherit normal host intervals, timeouts and HTTP behavior.
    """
    configs = [s for s in load_board_sources(sources_path) if s.enabled]
    if not configs:
        return [], ["No enabled life-sciences PhD providers"]
    if len(configs) > MAX_SOURCES:
        raise ValueError("Too many enabled life-sciences sources")
    posts: list[JobPostSchema] = []
    errors: list[str] = []
    semaphore = asyncio.Semaphore(3)
    async with build_http(http_config) as http:
        async def one(source: Any) -> tuple[list[JobPostSchema], list[str]]:
            if source.type not in ("rss", "link_scan"):
                return [], [f"{source.name}: unsupported scraper type"]
            scraper = SCRAPERS[source.type](source, http)
            async with semaphore:
                try:
                    result, _ = await asyncio.wait_for(
                        scraper.run(), timeout=min(http_config.source_timeout, 120),
                    )
                except Exception as exc:  # noqa: BLE001 - isolate provider outages
                    return [], [f"{source.name}: {type(exc).__name__}"]
            problems = (
                len(scraper.discovery_fetch_errors) +
                len(scraper.discovery_parse_errors) +
                len(scraper.discovery_limits)
            )
            warnings = [f"{source.name}: {problems} discovery issues"] if problems else []
            return result[:MAX_PER_SOURCE], warnings

        results = await asyncio.gather(*(one(config) for config in configs))
    for found, problems in results:
        posts.extend(found)
        errors.extend(problems)
    return posts[:MAX_TOTAL], errors


def poll_life_sciences(
    journal_path: str | Path, *, sources_path: str | Path,
    http_config: HttpConfig,
) -> tuple[int, list[str]]:
    """Append vetted life-sciences PhDs to the existing durable career journal.

    Preserves economics/other career records and first-seen timestamps. Only
    posts first discovered after subscription are eligible for new alerts.
    """
    posts, errors = asyncio.run(discover(sources_path, http_config))
    matches: dict[str, dict[str, str]] = {}
    for post in posts:
        item = classify_post(post)
        if item:
            matches.setdefault(item["key"], item)
    # A malformed non-life-sciences row cannot permanently block discovery.
    previous = load_career(journal_path, tolerant=True)
    return save_career(journal_path, previous, list(matches.values())), errors
