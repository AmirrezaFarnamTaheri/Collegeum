"""EURAXESS search-shard honesty and bounded, sanitized query evidence."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from predoc_pipeline.ingest.life_sciences import load_life_sources
from tools.probe_life_sciences_sources import check_sources


class Client:
    def __init__(self, pages: dict[str, tuple[int, str]]):
        self.pages = pages
        self.calls: list[str] = []

    def get(self, url: str, *, use_cache: bool = False):
        assert use_cache is False
        self.calls.append(url)
        status, html = self.pages[url]
        return SimpleNamespace(status=status, ok=status == 200, text=html,
                               error="" if status == 200 else "unavailable")


def config(tmp_path: Path) -> Path:
    path = tmp_path / "life_sciences.toml"
    path.write_text(
        '[[board]]\n'
        'name = "life_filtered"\n'
        'type = "link_scan"\n'
        'enabled = true\n'
        'query_result_diversity_required = true\n'
        'urls = ["https://example.org/search?f%5B0%5D=keywords%3Aepigenetics", '
        '"https://example.org/search?f%5B0%5D=keywords%3Agenomics"]\n'
        "link_pattern = 'example[.]org/jobs/[0-9]+$'\n",
        encoding="utf-8",
    )
    return path


def page(*rows: tuple[int, str], total: int = 70) -> str:
    links = "".join(
        f'<a href="/jobs/{id_value}">{title}</a>' for id_value, title in rows
    )
    return f"<html><h2>Search results ({total})</h2>{links}</html>"


def test_every_enabled_euraxess_keyword_shard_is_guarded():
    root = Path(__file__).resolve().parents[2]
    sources = load_life_sources(root / "config/life_sciences.toml")
    euraxess = [s for s in sources if s.enabled and
                (s.name == "life_euraxess" or s.name.startswith("life_euraxess_"))]
    assert len(euraxess) == 6
    assert all(s.opt("query_result_diversity_required") is True for s in euraxess)


def test_probe_reports_ignored_keyword_pages_as_partial_without_leaking_job_urls(tmp_path):
    urls = [
        "https://example.org/search?f%5B0%5D=keywords%3Aepigenetics",
        "https://example.org/search?f%5B0%5D=keywords%3Agenomics",
    ]
    html = page((11, "Research Associate"), (22, "Doctoral Researcher"), total=7412)
    client = Client({url: (200, html) for url in urls})
    report = check_sources(client, config(tmp_path), names={"life_filtered"},
                           limit=1, detail_sample_limit=0)
    observed = report["sources"]["life_filtered"]
    assert observed["status"] == "partial"
    assert observed["query_result_signal"] == "identical_nonempty"
    assert observed["vacancy_links"] == 2
    assert observed["endpoints"][0]["declared_result_count"] == 7412
    assert observed["endpoints"][1]["declared_result_count"] == 7412
    assert observed["endpoints"][0]["keyword_in_visible_text"] is False
    assert client.calls == urls
    assert "/jobs/11" not in json.dumps(report)
    assert "/jobs/22" not in json.dumps(report)


def test_probe_distinct_search_results_are_retained_without_claiming_keyword_verification(
    tmp_path,
):
    urls = [
        "https://example.org/search?f%5B0%5D=keywords%3Aepigenetics",
        "https://example.org/search?f%5B0%5D=keywords%3Agenomics",
    ]
    client = Client({
        urls[0]: (200, page((11, "PhD epigenetics"), total=12)),
        urls[1]: (200, page((22, "PhD in genomics"), total=16)),
    })
    report = check_sources(client, config(tmp_path), names={"life_filtered"},
                           limit=1, detail_sample_limit=0)
    observed = report["sources"]["life_filtered"]
    assert observed["status"] == "ok"
    assert observed["query_result_signal"] == "distinct_nonempty"
    assert observed["vacancy_links"] == 2
    assert [x["declared_result_count"] for x in observed["endpoints"]] == [12, 16]
    assert all(x["keyword_in_visible_text"] is True for x in observed["endpoints"])
    assert len(client.calls) == 2


def test_probe_partial_http_failure_never_misdiagnoses_filter_overlap(tmp_path):
    urls = [
        "https://example.org/search?f%5B0%5D=keywords%3Aepigenetics",
        "https://example.org/search?f%5B0%5D=keywords%3Agenomics",
    ]
    client = Client({
        urls[0]: (200, page((11, "PhD researcher"))),
        urls[1]: (403, ""),
    })
    observed = check_sources(client, config(tmp_path), limit=1,
                             detail_sample_limit=0)["sources"]["life_filtered"]
    assert observed["status"] == "partial"
    assert observed["query_result_signal"] == "indeterminate"
    assert observed["endpoints"][1]["status"] == "http_error"
