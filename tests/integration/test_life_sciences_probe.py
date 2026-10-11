"""Offline regression suite for the optional live Life Sciences source probe."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.probe_life_sciences_sources import (
    candidate_links,
    check_sources,
    feed_entries,
)

CATALOG = Path(__file__).resolve().parents[2] / "config/life_sciences.toml"


def test_probe_counts_link_anchors_only() -> None:
    text = (
        "<script>https://example.org/jobs/1234</script>"
        "<div><a href='/jobs/4532'>PhD in genomics</a></div>"
        "<a href='javascript:alert(1)'>PhD in genetics</a>"
        "<a href='/team/person'>About us</a>"
    )
    assert candidate_links(text, "https://example.org/jobs", r"example.org/jobs/\d+") == 1


def test_probe_counts_feed_entries_only() -> None:
    assert feed_entries(
        "<rss><channel><title>Jobs</title><item><title>PhD</title>"
        "</item><item><title>Postdoc</title></item></channel></rss>"
    ) == 2
    assert feed_entries("<rss><channel><title>Jobs</title></channel></rss>") == 0
    assert feed_entries("<script>no feed</script>") == 0


def test_probe_distinguishes_robots_denials_and_vacancy_links() -> None:
    class Client:
        def get(self, url: str, **_kwargs):
            if "academictransfer.com" in url:
                return SimpleNamespace(
                    ok=False, status=999, text="", error="blocked by robots.txt",
                )
            if "mpg.de" in url:
                return SimpleNamespace(
                    ok=True, status=200,
                    text='<a href="https://www.mpg.de/26905386/postdoc-position-'
                         'ultrafast-x-ray">Postdoc position (m/f/d)</a>',
                    error="",
                )
            return SimpleNamespace(
                ok=True, status=200,
                text="<a href='https://euraxess.ec.europa.eu/jobs/123456'>"
                     "PhD in epigenetics</a>",
                error="",
            )

    result = check_sources(Client(), CATALOG, region="core", limit=3)
    assert result["enabled_in_scope"] == 10
    assert result["checked"] == 3
    assert result["sources"]["life_euraxess"]["status"] == "ok"
    assert result["sources"]["life_academictransfer"]["status"] == "blocked_robots"
    assert result["sources"]["life_max_planck"]["vacancy_links"] == 1
    assert all("chat_id" not in item for item in result["sources"].values())


def test_empty_javascript_shell_is_not_marked_working() -> None:
    class Client:
        def get(self, _url: str, **_kwargs):
            return SimpleNamespace(
                ok=True, status=200,
                text="<html><script>location='/jobs/123'</script></html>",
                error="",
            )

    result = check_sources(Client(), CATALOG, region="core", limit=2)
    assert all(
        item["status"] == "no_recognized_vacancy_links"
        for item in result["sources"].values()
    )


@pytest.mark.parametrize("region", ["../../etc", "", "unrecognized", "uk"])
def test_probe_rejects_unknown_regions(region: str) -> None:
    with pytest.raises(ValueError, match="unknown source region"):
        check_sources(None, CATALOG, region=region)


@pytest.mark.parametrize("limit", [0, -1, 17, 1000])
def test_probe_rejects_unbounded_requests(limit: int) -> None:
    with pytest.raises(ValueError, match="limit must be between"):
        check_sources(None, CATALOG, limit=limit)


def test_probe_all_enabled_sources_across_disjoint_offset_pages() -> None:
    class Client:
        def get(self, _url: str, **_kwargs):
            return SimpleNamespace(
                ok=False, status=999, text="", error="blocked by robots.txt",
            )

    ids: set[str] = set()
    offset = 0
    while True:
        report = check_sources(Client(), CATALOG, limit=16, offset=offset)
        assert report["offset"] == offset
        assert len(set(report["sources"]) & ids) == 0
        ids.update(report["sources"])
        if report["next_offset"] is None:
            break
        offset = report["next_offset"]
    assert len(ids) == 37


@pytest.mark.parametrize("offset", [-1, 257, 999])
def test_probe_rejects_unbounded_offsets(offset: int) -> None:
    with pytest.raises(ValueError, match="offset must be between"):
        check_sources(None, CATALOG, offset=offset)
