"""Read-only validation of the new institutional monitors from the repo root."""

import asyncio
import json
from pathlib import Path

from bs4 import BeautifulSoup

from predoc_pipeline.boards.collector import _collect, _scrape_all
from predoc_pipeline.boards.config import load_board_sources, load_preferences
from predoc_pipeline.boards.http import HttpClient
from predoc_pipeline.boards.scrapers import SCRAPERS

NAMES = {
    "aarhus_jobs",
    "gothenburg_jobs",
    "umea_usbe_jobs",
    "linkoping_jobs",
    "duke_jobs",
    "trinity_cambridge_jobs",
    "bruegel_jobs",
}
ROOT = Path(__file__).parent / "institutions"


def save_json(name, data):
    (ROOT / name).write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )


async def main():
    sources = [c for c in load_board_sources(Path("config/sources.toml")) if c.name in NAMES]
    async with HttpClient(timeout=20, max_retries=0) as http:
        original = http.get_text
        captured = {}

        async def capture(url):
            text = await original(url)
            captured[url] = text
            return text

        http.get_text = capture
        results = await _scrape_all([SCRAPERS[c.type](c, http) for c in sources], 3, 90)
        details = []
        for result in results:
            print(result.scraper.name, result.as_stats())
            if result.posts:
                post = next(
                    (p for p in result.posts if "Economics" in p.title or "Political" in p.title),
                    result.posts[0],
                )
                try:
                    detail = await result.scraper.fetch_detail(post)
                    details.append(
                        dict(
                            source=post.source,
                            title=post.title,
                            url=post.url,
                            characters=len(detail or ""),
                            sample=(detail or "")[:900],
                            final_url=post.extra.get("final_url"),
                        )
                    )
                except Exception as exc:
                    details.append(dict(source=post.source, url=post.url, error=str(exc)))
        save_json(
            "discovery.json",
            [
                dict(
                    source=r.scraper.name,
                    stats=r.as_stats(),
                    posts=[
                        dict(
                            title=p.title,
                            url=p.url,
                            deadline=p.deadline,
                            date_posted=p.date_posted,
                            deadline_text=p.deadline_text,
                        )
                        for p in r.posts
                    ],
                )
                for r in results
            ],
        )
        save_json("details.json", details)
        for cfg in sources:
            soup = BeautifulSoup(captured[cfg.opt("url")], "lxml")
            out = BeautifulSoup("<html><body></body></html>", "lxml")
            if cfg.type == "emply_embedded":
                for script in soup.select("script"):
                    if ".vacancies =" in script.get_text():
                        out.body.append(script)
            elif cfg.type == "text_table":
                out.body.append(soup.select_one(cfg.opt("table_selector")))
            else:
                for item in soup.select(cfg.opt("selectors")["item"]):
                    if cfg.name == "gothenburg_jobs":
                        wrapper = out.new_tag("table", attrs={"class": "table--vacancies"})
                    elif cfg.name == "umea_usbe_jobs" and item.name == "p":
                        wrapper = out.new_tag("div", attrs={"class": "textblock"})
                    elif cfg.name == "bruegel_jobs":
                        wrapper = out.new_tag("div", attrs={"class": "o-content-from-editor"})
                    else:
                        wrapper = out.body
                    if wrapper is not out.body:
                        out.body.append(wrapper)
                    wrapper.append(item)
            for item in out.select("img, svg, style"):
                item.decompose()
            fixture = Path("tests/fixtures/boards/institutions") / f"{cfg.name}.html"
            fixture.parent.mkdir(exist_ok=True)
            fixture.write_text(str(out), encoding="utf-8")
        run = await _collect(
            sources, load_preferences(Path("config/preferences.toml")), lambda url: False, http
        )
        save_json(
            "collection.json",
            dict(
                stats=run.stats,
                rejected=run.rejected,
                deferred=run.deferred,
                emitted=len(run.items),
                items=[
                    dict(url=i.source_url, title=i.title, hints=i.hints, characters=len(i.text))
                    for i in run.items
                ],
            ),
        )
        print("collection", run.rejected, "deferred", run.deferred, "items", len(run.items))
        print("details", [(x["source"], x.get("characters"), x.get("error")) for x in details])


if __name__ == "__main__":
    asyncio.run(main())
