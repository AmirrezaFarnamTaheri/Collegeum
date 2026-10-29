"""Recover the official UCPH job board without inventing application identities."""

import asyncio
from pathlib import Path

from predoc_pipeline.boards.collector import _scrape_all
from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.scrapers import SCRAPERS


class FixtureHttp:
    async def get_text(self, url):
        assert url == "https://jobportal.ku.dk/alle-opslag/"
        return """
        <h1>Alle ledige stillinger</h1>
        <table>
          <tr><td><a href="/alle-opslag/?show=167779">Postdoctoral Positions in
          Statistics and the Mathematics of Insurance and Economics</a></td>
          <td>Department of Mathematical Sciences</td>
          <td>15-11-2026</td></tr>
          <tr><td><a href="/alle-opslag/?show=167780">Postdoctoral Positions
          in Mathematics</a></td><td>Department of Mathematical Sciences</td>
          <td>15-11-2026</td></tr>
          <tr><td><a href="/alle-opslag/">Alle stillinger</a></td></tr>
        </table>
        """


def test_copenhagen_uses_job_specific_links_on_official_danish_portal():
    cfg = next(s for s in load_board_sources(Path("config/sources.toml"))
               if s.name == "copenhagen")
    assert cfg.opt("url") == "https://jobportal.ku.dk/alle-opslag/"
    result = asyncio.run(_scrape_all(
        [SCRAPERS[cfg.type](cfg, FixtureHttp())], 1, 5,
    ))[0]
    assert result.ok
    assert len(result.posts) == 2
    assert [x.url for x in result.posts] == [
        "https://jobportal.ku.dk/alle-opslag?show=167779",
        "https://jobportal.ku.dk/alle-opslag?show=167780",
    ]
    assert "Insurance and Economics" in result.posts[0].title
    assert result.posts[0].country == "Denmark"
