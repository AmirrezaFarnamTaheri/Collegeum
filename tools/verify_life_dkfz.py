"""Live read-only DKFZ PhD index verification via the shared HTML adapter.

Fail closed when official job anchors are absent or robot policy denies access.
Does not write publication, journal, private subscriber or Telegram state.
"""
from __future__ import annotations

import json

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper
from predoc_pipeline.ingest.http import PoliteClient


def main() -> None:
    source = next(
        board for board in load_board_sources("config/life_sciences.toml")
        if board.name == "life_dkfz"
    )
    with PoliteClient(
        user_agent="Collegeum-LifeSourceProbe/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)",
        timeout=18.0, per_host_delay=3, respect_robots=True,
    ) as http:
        url = str(source.opt("url"))
        response = http.get(url, use_cache=False)
        if not response.ok:
            raise RuntimeError(
                f"DKFZ source not usable on runner: {response.error or response.status}"
            )
        scraper = LinkScanScraper(source, http)
        jobs = scraper.parse_postings([(url, response.text)])
        output = {
            "source": source.name, "http_status": response.status,
            "doctoral_candidates": len(jobs),
            "official_job_urls": [job.url for job in jobs[:8]],
            "discovery_parse_errors": scraper.discovery_parse_errors,
        }
        print(json.dumps(output, indent=2))
        if not jobs or scraper.discovery_parse_errors:
            raise RuntimeError("DKFZ index did not provide parseable doctoral applications")
        if not all(job.extra.get("require_deadline") for job in jobs):
            raise RuntimeError("strict deadline protection not applied")


if __name__ == "__main__":
    main()
