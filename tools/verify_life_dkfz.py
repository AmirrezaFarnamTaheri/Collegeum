"""Read-only live verification of DKFZ's official d.vinci RSS vacancies.

This checks source-index integrity and doctoral eligibility separately.
It never updates journals, subscriber state or Telegram delivery receipts.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from predoc_pipeline.boards.config import HttpConfig, load_board_sources
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.ingest.life_sciences import classify_post, discover


def assess_dkfz_probe(
    posts: list[JobPostSchema],
    errors: list[str],
    diagnostics: dict[str, dict[str, Any]],
    *,
    on_date: date | None = None,
) -> dict[str, Any]:
    """Require complete, official RSS discovery without claiming all jobs are PhDs."""
    health = diagnostics.get("life_dkfz")
    if not isinstance(health, dict) or health.get("status") != "discovered":
        raise RuntimeError("DKFZ source did not complete healthy RSS discovery")
    if errors or health.get("discovery_issues") or health.get("detail_failures"):
        raise RuntimeError("DKFZ source had discovery or vacancy-detail errors")
    if not posts:
        raise RuntimeError("DKFZ official RSS discovery returned no vacancy links")

    urls = [post.url for post in posts]
    if len(set(urls)) != len(urls):
        raise RuntimeError("DKFZ RSS contained duplicate vacancy URLs")
    for post in posts:
        try:
            link = urlsplit(post.url)
            trusted = (
                link.scheme == "https"
                and link.hostname == "jobs.dkfz.de"
                and link.port in (None, 443)
                and link.username is None
                and link.password is None
            )
        except ValueError:
            trusted = False
        if not trusted or post.source != "life_dkfz":
            raise RuntimeError("DKFZ vacancy URL has untrusted provenance")
        if post.extra.get("require_deadline") is not True:
            raise RuntimeError("DKFZ vacancy is missing its strict deadline gate")

    matches = [
        accepted for post in posts
        if (accepted := classify_post(post, today=on_date)) is not None
    ]
    if any(
        accepted["country"] != "Germany" or not accepted.get("deadline")
        for accepted in matches
    ):
        raise RuntimeError("DKFZ doctoral eligibility lacks country or deadline evidence")
    return {
        "source": "life_dkfz",
        "status": health["status"],
        "general_vacancies": len(posts),
        "unique_urls": len(set(urls)),
        "eligible_doctoral_matches": len(matches),
        "discovery_issues": health.get("discovery_issues", 0),
        "detail_failures": health.get("detail_failures", 0),
    }


def main() -> None:
    source = next(
        board for board in load_board_sources("config/life_sciences.toml")
        if board.name == "life_dkfz"
    )
    if not source.enabled or source.type != "rss":
        raise RuntimeError("DKFZ official RSS collector is not enabled")
    if (
        source.opt("url") != "https://jobs.dkfz.de/en/jobs"
        or source.opt("allowed_link_hosts") != ["jobs.dkfz.de"]
        or not source.opt("rss_user_agent")
        or source.opt("require_deadline") is not True
    ):
        raise RuntimeError("DKFZ official identity or eligibility settings changed")

    diagnostics: dict[str, dict[str, Any]] = {}
    posts, errors = asyncio.run(discover(
        "config/life_sciences.toml",
        HttpConfig(timeout=18, max_retries=0, source_timeout=90),
        selected_names={"life_dkfz"},
        diagnostics=diagnostics,
    ))
    result = assess_dkfz_probe(posts, errors, diagnostics)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
