"""Read-only runner verification of the October 2026 source candidate cohorts.

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
from predoc_pipeline.boards.scrapers.university_ats import parse_workday_url
from predoc_pipeline.ingest.http import PoliteClient

MANIFEST = Path("config/source_expansion_20261029.csv")
NON_US_MANIFEST = Path("config/non_us_sources_20261029.csv")
REGISTRY = Path("config/sources.toml")
MAX_BATCH = 10


def robots_allow_source(source: object) -> bool:
    """Fail closed if robots policy forbids either landing or Workday API access."""
    listing = source.opt("url")
    if not listing:
        return False
    urls = [listing]
    if source.type == "workday":
        host, tenant, site, _ = parse_workday_url(listing)
        urls.append(f"https://{host}/wday/cxs/{tenant}/{site}/jobs")
    with PoliteClient(
        user_agent="CollegeumSourceProbe/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)",
        timeout=10, per_host_delay=2.0, respect_robots=True,
    ) as client:
        return all(client.allowed(url) for url in urls)


def read_candidates(path: Path = MANIFEST) -> list[dict[str, str]]:
    """Accept only the reviewed manifests and their fixed source-type counts."""
    expected = {
        MANIFEST: (30, 19, 11),
        NON_US_MANIFEST: (21, 0, 21),
    }
    if path not in expected:
        raise ValueError("Unknown source-expansion manifest")
    with path.open(newline="", encoding="utf-8") as file:
        records = list(csv.DictReader(file))
    names = [r["name"] for r in records]
    total, workday, link_scan = expected[path]
    if len(records) != total or len(names) != len(set(names)):
        raise ValueError(f"Source manifest requires {total} unique names")
    if sum(r["type"] == "workday" for r in records) != workday:
        raise ValueError(f"Source manifest requires {workday} Workday sites")
    if sum(r["type"] == "link_scan" for r in records) != link_scan:
        raise ValueError(f"Source manifest requires {link_scan} link-scan sites")
    for row in records:
        if row.get("enabled") != "false" or not row.get("url", "").startswith("https://"):
            raise ValueError("Source manifest includes active or invalid entries")
    return records


async def probe_candidates(
    *, manifest: Path = MANIFEST, registry: Path = REGISTRY,
    offset: int = 0, limit: int = MAX_BATCH,
) -> dict:
    candidates = read_candidates(manifest)
    if limit < 1 or limit > MAX_BATCH or offset < 0 or offset > len(candidates):
        raise ValueError("invalid bounded probe selection")
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
            if source is None or source.type != record["type"] or (
                source.opt("url") != record["url"]
            ):
                results[name] = {"status": "config_mismatch", "jobs": 0}
                continue
            if source.type not in SCRAPERS:
                results[name] = {"status": "unsupported_type", "jobs": 0}
                continue
            if source.type == "link_scan" and source.opt("link_pattern") == "^$":
                # Deliberately unimplemented ATS parsers must not issue network
                # requests or be mistaken for healthy-empty sources.
                results[name] = {"status": "parser_not_configured", "jobs": 0}
                continue
            if not await asyncio.to_thread(robots_allow_source, source):
                results[name] = {"status": "blocked_by_robots_or_unknown", "jobs": 0}
                continue
            response = (await _scrape_all([SCRAPERS[source.type](source, client)], 1, 75))[0]
            posts = response.posts
            valid = [p for p in posts if p.url.startswith("https://") and p.title.strip()]
            status = ("error" if not response.ok else
                      "no_recognized_jobs" if not valid else
                      "needs_eligibility_review")
            results[name] = {
                "status": status,
                "enabled": source.enabled,
                "jobs": len(valid),
                "unique_job_urls": len({p.url for p in valid}),
                "sample": [{"title": p.title, "url": p.url} for p in valid[:5]],
                "failure_stage": response.failure_stage,
                "failure_counts": response.as_stats()["failure_counts"],
            }
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "offset": offset, "limit": limit, "candidate_count": len(candidates),
        "checked": len(selected), "manifest": str(manifest),
        "next_offset": min(len(candidates), offset + limit)
        if offset + limit < len(candidates) else None, "sources": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST,
                        choices=[MANIFEST, NON_US_MANIFEST])
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("build/source-expansion-probe.json"))
    args = parser.parse_args()
    report = asyncio.run(probe_candidates(
        manifest=args.manifest, offset=args.offset, limit=args.limit,
    ))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
