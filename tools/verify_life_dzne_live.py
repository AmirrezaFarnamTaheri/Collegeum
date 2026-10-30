"""Read-only live acceptance for DZNE d.vinci sitemap and PhD jobPublication XML.

No Telegram, subscriber state, persistence or publication. A stale or invalid
job URL is not counted as an active doctoral vacancy.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

from predoc_pipeline.boards.config import HttpConfig
from predoc_pipeline.ingest.http import PoliteClient
from predoc_pipeline.ingest.life_sciences import classify_post, discover, load_life_sources

NAME = "life_special_de_dzne"
EXPECTED_CURRENT_ID = "101677"
SITEMAP = "https://jobs.dzne.de/sitemap.xml"
UA = "Collegeum-LSSourceProbe/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
JOB = re.compile(r"^https://jobs\.dzne\.de/(?:en|de)/jobs/([1-9]\d{4,8})/[a-z0-9-]+/?$")


async def main() -> None:
    config = next(
        s for s in load_life_sources(Path("config/life_sciences.toml"))
        if s.name == NAME
    )
    if not config.enabled or config.type != "dzne_sitemap":
        raise RuntimeError("DZNE official source not enabled")
    with PoliteClient(
        user_agent=UA, timeout=15, per_host_delay=2, respect_robots=True,
    ) as client:
        if not client.allowed(SITEMAP):
            raise RuntimeError("DZNE sitemap denied by robots policy")
        result = client.get(SITEMAP, use_cache=False)
        if not result.ok:
            raise RuntimeError("Official DZNE sitemap unavailable or denied")

    diagnostics = {}
    posts, errors = await discover(
        Path("config/life_sciences.toml"),
        HttpConfig(timeout=16, max_retries=0, source_timeout=55),
        selected_names={NAME}, diagnostics=diagnostics,
    )
    status = diagnostics.get(NAME, {})
    qualified = [item for post in posts
                 if (item := classify_post(post, today=datetime.now(UTC).date()))]
    ids = [match.group(1) for post in posts if (match := JOB.fullmatch(post.url))]
    payload = {
        "source": NAME,
        "status": status.get("status"),
        "error_count": len(errors),
        "errors": errors,
        "vacancies": len(posts),
        "doctoral_candidates": status.get("doctoral_candidates"),
        "eligible_phds": len(qualified),
        "jobs": [
            {
                "url": p.url, "date_posted": p.date_posted.isoformat() if p.date_posted else None,
                "deadline": p.deadline.isoformat() if p.deadline else None,
                "title": p.title,
            }
            for p in posts[:12]
        ],
        "no_private_writes": True,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if errors or status.get("status") not in {"discovered", "verified_empty"}:
        raise RuntimeError("DZNE job feed failed, partial, or erroneously empty")
    if len(ids) != len(posts):
        raise RuntimeError("DZNE vacancy URL or employer identity failed validation")
    if datetime.now(UTC).date() <= date(2026, 12, 1) and EXPECTED_CURRENT_ID not in ids:
        raise RuntimeError("Current DZNE PhD requisition 101677 absent from official feed")
    if any(q["source"] != NAME or q.get("funding_status") != "unverified"
           for q in qualified):
        raise RuntimeError("DZNE PhD source or funding status incorrectly inferred")


if __name__ == "__main__":
    asyncio.run(main())
