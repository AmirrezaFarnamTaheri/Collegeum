"""Offline assurance: exact URL overlap is evidence, never job-identity merging."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tools.probe_life_sciences_sources import check_sources


def catalog(tmp_path: Path) -> Path:
    result = tmp_path / "life_sciences.toml"
    result.write_text(
        "[[board]]\n"
        'name = "life_first"\n'
        'type = "link_scan"\n'
        'enabled = true\n'
        'urls = ["https://example.org/search?q=a", "https://example.org/search?q=b"]\n'
        "link_pattern = 'example[.]org/jobs/[0-9]+$'\n\n"
        "[[board]]\n"
        'name = "life_second"\n'
        'type = "link_scan"\n'
        'enabled = true\n'
        'urls = ["https://example.org/search?q=c", "https://example.org/search?q=d"]\n'
        "link_pattern = 'example[.]org/jobs/[0-9]+$'\n",
        encoding="utf-8",
    )
    return result


class Client:
    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping
        self.calls: list[str] = []

    def get(self, url: str, *, use_cache: bool = False):
        assert not use_cache
        self.calls.append(url)
        if url not in self.mapping:
            raise AssertionError("Unexpected detail request")
        return SimpleNamespace(status=200, ok=True, text=self.mapping[url], error="")


def anchors(*ids: int) -> str:
    return "".join(f"<a href='/jobs/{value}'>Research job</a>" for value in ids)


def test_search_query_overlap_and_cross_view_identity_are_reported_without_urls(tmp_path):
    client = Client({
        "https://example.org/search?q=a": anchors(11, 22),
        "https://example.org/search?q=b": anchors(11, 22),
        "https://example.org/search?q=c": anchors(11, 22),
        "https://example.org/search?q=d": anchors(11, 33),
    })
    report = check_sources(client, catalog(tmp_path), names={"life_first", "life_second"},
                           limit=2, detail_sample_limit=0)
    first, second = report["sources"]["life_first"], report["sources"]["life_second"]
    assert first["vacancy_links"] == 2
    assert first["duplicate_link_appearances_across_query_pages"] == 2
    assert second["vacancy_links"] == 3
    assert second["duplicate_link_appearances_across_query_pages"] == 1
    assert report["cross_source_overlap"] == {
        "source_pairs_examined": 1,
        "observed_source_unique_link_total": 5,
        "distinct_observed_link_urls": 3,
        "pairwise_shared_link_counts": [
            {"left": "life_first", "right": "life_second", "shared_link_urls": 2},
        ],
    }
    assert len(client.calls) == 4
    assert "/jobs/" not in json.dumps(report["cross_source_overlap"])


def test_disjoint_search_views_have_no_overlap_without_inferred_duplicates(tmp_path):
    client = Client({
        "https://example.org/search?q=a": anchors(11),
        "https://example.org/search?q=b": anchors(11),
        "https://example.org/search?q=c": anchors(22),
        "https://example.org/search?q=d": anchors(22),
    })
    report = check_sources(client, catalog(tmp_path), limit=2)
    overlap = report["cross_source_overlap"]
    assert overlap["source_pairs_examined"] == 1
    assert overlap["pairwise_shared_link_counts"] == []
    assert overlap["distinct_observed_link_urls"] == 2
    assert overlap["observed_source_unique_link_total"] == 2
    assert report["sources"]["life_first"]["duplicate_link_appearances_across_query_pages"] == 1
    assert report["sources"]["life_second"]["duplicate_link_appearances_across_query_pages"] == 1


def test_empty_search_views_report_zero_without_attempting_details(tmp_path):
    urls = {f"https://example.org/search?q={q}": "<html>No vacancy anchors</html>"
            for q in "abcd"}
    client = Client(urls)
    report = check_sources(client, catalog(tmp_path), names={"life_first", "life_second"},
                           limit=2, detail_sample_limit=0)
    assert report["cross_source_overlap"]["distinct_observed_link_urls"] == 0
    assert report["cross_source_overlap"]["pairwise_shared_link_counts"] == []
    assert all(entry["duplicate_link_appearances_across_query_pages"] == 0
               for entry in report["sources"].values())
    assert len(client.calls) == 4
