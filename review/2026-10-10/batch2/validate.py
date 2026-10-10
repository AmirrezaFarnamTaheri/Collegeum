"""Run only the new sources through production collection without publishing."""

import asyncio
import json
from pathlib import Path

from predoc_pipeline.boards.collector import _collect, _scrape_all
from predoc_pipeline.boards.config import load_board_sources, load_preferences
from predoc_pipeline.boards.http import HttpClient
from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper

NAMES = {"warwick_jobs", "bank_canada_jobs", "sciencespo_jobs"}


async def main():
    sources = [c for c in load_board_sources(Path("config/sources.toml")) if c.name in NAMES]
    async with HttpClient(timeout=20, max_retries=0) as http:
        results = await _scrape_all([LinkScanScraper(c, http) for c in sources], 3, 60)
        discovery = [
            dict(
                source=r.scraper.name,
                stats=r.as_stats(),
                posts=[
                    dict(
                        title=p.title,
                        url=p.url,
                        deadline=str(p.deadline) if p.deadline else None,
                        deadline_text=p.deadline_text,
                    )
                    for p in r.posts
                ],
            )
            for r in results
        ]
        Path(__file__).with_name("discovery.json").write_text(
            json.dumps(discovery, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        run = await _collect(
            sources, load_preferences(Path("config/preferences.toml")), lambda url: False, http
        )
        evidence = dict(
            stats=run.stats,
            rejected=run.rejected,
            known=run.known,
            deferred=run.deferred,
            emitted=len(run.items),
            items=[
                dict(url=i.source_url, title=i.title, hints=i.hints, detail_characters=len(i.text))
                for i in run.items
            ],
        )
        Path(__file__).with_name("collection.json").write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        print(json.dumps({k: v for k, v in evidence.items() if k != "items"}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
