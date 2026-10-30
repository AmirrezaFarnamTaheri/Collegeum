"""Read-only IFAU vacancy acceptance: never present a JS shell as empty."""
from __future__ import annotations

import json

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper
from predoc_pipeline.ingest.http import PoliteClient


def main() -> None:
    cfg = next(c for c in load_board_sources("config/sources.toml")
               if c.name == "ifau_sweden_labour")
    with PoliteClient(
        user_agent="Collegeum-SourceProbe/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)",
        timeout=18, per_host_delay=3, respect_robots=True,
    ) as client:
        response = client.get(str(cfg.opt("url")), use_cache=False)
        if not response.ok:
            raise RuntimeError(f"Official IFAU index unreachable: {response.error or response.status}")
        spider = LinkScanScraper(cfg, client)
        jobs = spider.parse_postings([(str(cfg.opt("url")), response.text)])
        outcome = {
            "source": cfg.name, "status": response.status,
            "vacancies": len(jobs),
            "verified_empty": spider.verified_empty_evidence,
            "parse_errors": spider.discovery_parse_errors,
            "urls": [p.url for p in jobs[:6]],
        }
        print(json.dumps(outcome, indent=2))
        if spider.discovery_parse_errors or (not jobs and not spider.verified_empty_evidence):
            raise RuntimeError("IFAU page is not a verified empty recruitment feed")
        if jobs and not all(job.url.startswith(cfg.opt("url")) for job in jobs):
            raise RuntimeError("Unexpected IFAU job URL identity")


if __name__ == "__main__":
    main()
