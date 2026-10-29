"""Read-only runner verification of the 30 October 2026 source candidates.

This is discovery evidence, NOT an authorization to enable a source. Never
reads publication/subscriber state and never sends alerts. Partial Workday
pagination, schema drift and HTTP failures are explicit failed outcomes.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from predoc_pipeline.boards.collector import _scrape_all, build_http
from predoc_pipeline.boards.config import HttpConfig, load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS

MANIFEST = Path("config/source_expansion_20261029.csv")
REGISTRY = Path("config/sources.toml")
MAX_BATCH = 10


def read_candidates(path: Path = MANIFEST) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        records = list(csv.DictReader(file))
    names = [r["name"] for r in records]
    if len(records) != 30 or len(names) != len(set(names)):
        raise ValueError("Source candidate manifest must contain 30 unique names")
    if sum(r["type"] == "workday" for r in records) != 19:
        raise ValueError("Source candidate manifest must include 19 Workday sites")
    if sum(r["type"] == "link_scan" for r in records) != 11:
        raise ValueError("Source candidate manifest must include 11 link-scan sites")
    return records


async def probe_candidates(
    *, manifest: Path = MANIFEST, registry: Path = REGISTRY,
    offset: int = 0, limit: int = MAX_BATCH,
) -> dict:
    if limit < 1 or limit > MAX_BATCH or offset < 0 or offset > 30:
        raise ValueError("invalid bounded probe selection")
    candidates = read_candidates(manifest)
    registered = {s.name: s for s in load_board_sources(registry)}
    selected = candidates[offset:offset + limit]
    http_cfg = HttpConfig(timeout=12, max_retries=0, backoff_base=1,
                          default_min_interval=1.5, max_concurrent_sources=2,
                          source_timeout=75)
    results = {}
    async with build_http(http_cfg) as client:
        for record in selected:
            name = record["name"]
            source = registered.get(name)
            if source is None or source.enabled or source.type != record["type"] or (
                source.opt("url") != record["url"]
            ):
                results[name] = {"status": "config_mismatch", "jobs": 0}
                continue
            if source.type not in SCRAPERS:
                results[name] = {"status": "unsupported_type", "jobs": 0}
                continue
            response = (await _scrape_all([SCRAPERS[source.type](source, client)], 1, 75))[0]
            posts = response.posts
            valid = [p for p in posts if p.url.startswith("https://") and p.title.strip()]
            status = ("error" if not response.ok else
                      "no_recognized_jobs" if not valid else
                      "needs_eligibility_review")
            results[name] = {
                "status": status,
                "jobs": len(valid),
                "unique_job_urls": len({p.url for p in valid}),
                "sample": [{"title": p.title, "url": p.url} for p in valid[:5]],
                "failure_stage": response.failure_stage,
                "failure_counts": response.as_stats()["failure_counts"],
            }
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "offset": offset, "limit": limit, "candidate_count": len(candidates),
        "checked": len(selected), "next_offset": min(30, offset + limit)
        if offset + limit < 30 else None, "sources": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("build/source-expansion-probe.json"))
    args = parser.parse_args()
    report = asyncio.run(probe_candidates(offset=args.offset, limit=args.limit))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
