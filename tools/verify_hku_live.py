"""Read-only live HKU recruitment acceptance on a GitHub-hosted runner."""
from __future__ import annotations

import asyncio
import json

from predoc_pipeline.boards.collector import _scrape_all, build_http
from predoc_pipeline.boards.config import HttpConfig, load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS
from predoc_pipeline.ingest.http import PoliteClient

NAME = "hku_econ_social_jobs"
JOB = "https://jobs.hku.hk/en/job/537693/research-assistant-i"


async def main() -> None:
    cfg = next(source for source in load_board_sources("config/sources.toml")
               if source.name == NAME)
    with PoliteClient(
        user_agent="CollegeumSourceProbe/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)",
        timeout=12, respect_robots=True, per_host_delay=2,
    ) as polite:
        if not polite.allowed(cfg.opt("url")):
            raise RuntimeError("HKU careers crawl denied or robots policy unavailable")
    httpcfg = HttpConfig(max_retries=0, max_concurrent_sources=1,
                         source_timeout=50, timeout=15)
    async with build_http(httpcfg) as http:
        result = (await _scrape_all([SCRAPERS[cfg.type](cfg, http)], 1, 50))[0]
    record = {
        "source": NAME, "ok": result.ok, "error": result.error,
        "status": result.as_stats().get("status"),
        "jobs": len(result.posts),
        "urls": [post.url for post in result.posts[:15]],
        "failure_counts": result.as_stats()["failure_counts"],
    }
    print(json.dumps(record, indent=2))
    if (not result.ok or JOB not in {p.url for p in result.posts}
            or result.as_stats()["failure_counts"]["fetch"]
            or result.as_stats()["failure_counts"]["parse"]):
        raise RuntimeError("HKU runner did not confirm the expected open economics role")


if __name__ == "__main__":
    asyncio.run(main())
