"""Read-only official acceptance: Helmholtz bilingual recruitment API.

Only the existing public employer widgets and B-ite job search are contacted.
Never access accounts, messages, subscriptions, persistent publication state.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from urllib.parse import urlsplit

from predoc_pipeline.boards.collector import _scrape_all, build_http
from predoc_pipeline.boards.config import HttpConfig
from predoc_pipeline.boards.scrapers.bite_jobs import BiteJobsScraper
from predoc_pipeline.ingest.http import PoliteClient
from predoc_pipeline.ingest.life_sciences import classify_post, load_life_sources

EN = (
    "https://cs-assets.b-ite.com/helmholtz-zentrum-muenchen/"
    "jobs-api/main-listing-en.js"
)
DE = (
    "https://cs-assets.b-ite.com/helmholtz-zentrum-muenchen/"
    "jobs-api/main-listing-de.js"
)
API = "https://jobs.b-ite.com/api/v1/postings/search"
HOST = "jobs.helmholtz-muenchen.de"
SOURCE = "life_special_de_helmholtz_munich"
UA = "Collegeum-LSSourceProbe/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)"


async def inspect() -> None:
    with PoliteClient(
        user_agent=UA, timeout=14, per_host_delay=2, respect_robots=True,
    ) as policy:
        allowed = {url: policy.allowed(url) for url in (EN, DE, API)}
    if not all(allowed.values()):
        raise RuntimeError("Helmholtz B-ite official public feed denied by robots policy")

    cfg = next(
        (x for x in load_life_sources("config/life_sciences.toml")
         if x.name == SOURCE), None,
    )
    if cfg is None or not cfg.enabled or cfg.type != "bite_jobs":
        raise RuntimeError("Expected existing enabled Helmholtz source")

    options = HttpConfig(
        timeout=16, max_retries=0, source_timeout=65,
        max_concurrent_sources=1, default_min_interval=1.5,
    )
    async with build_http(options) as http:
        result = (await _scrape_all(
            [BiteJobsScraper(cfg, http)], 1, 65,
        ))[0]
    posts = result.posts
    unique_urls = {post.url for post in posts}
    invalid = [
        post.url for post in posts
        if (
            urlsplit(post.url).hostname != HOST or
            urlsplit(post.url).scheme != "https" or
            not post.institution or post.institution != "Helmholtz Munich" or
            post.country != "Germany"
        )
    ]
    matched = [
        match for post in posts
        if (match := classify_post(post)) is not None
    ]
    report = {
        "source": SOURCE,
        "at": datetime.now(UTC).isoformat(),
        "robots_allowed": allowed,
        "health": result.as_stats(),
        "jobs": len(posts), "unique_urls": len(unique_urls),
        "invalid_urls": invalid[:10],
        "qualified_life_sciences_phd": len(matched),
        "qualified_titles": [x["title"] for x in matched[:12]],
        "titles": [p.title for p in posts[:24]],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not result.ok:
        raise RuntimeError("Official Helmholtz source fetch/parse/limit was degraded")
    if not posts or len(posts) != len(unique_urls) or invalid:
        raise RuntimeError("Official Helmholtz listing identities are invalid/empty")
    if len(posts) > 200:
        raise RuntimeError("Unexpected official Helmholtz scope expansion")


if __name__ == "__main__":
    asyncio.run(inspect())
