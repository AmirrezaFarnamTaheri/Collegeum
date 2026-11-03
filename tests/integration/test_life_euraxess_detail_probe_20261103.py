"""Safe, bounded read-only investigation of Life Sciences detail access."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.probe_life_sciences_sources import check_sources


def catalogue(tmp_path: Path) -> Path:
    path = tmp_path / "life_sciences.toml"
    path.write_text(
        "[[board]]\n"
        'name = "life_euraxess"\n'
        'type = "link_scan"\n'
        'enabled = true\n'
        'urls = ["https://example.org/search?q=epi", '
        '"https://example.org/search?q=genomics"]\n'
        "link_pattern = 'example[.]org/jobs/[0-9]+$'\n\n"
        "[[board]]\n"
        'name = "life_unrelated"\n'
        'type = "link_scan"\n'
        'enabled = true\n'
        'url = "https://different.org/jobs"\n'
        "link_pattern = 'different[.]org/jobs/[0-9]+$'\n\n"
        "[[board]]\n"
        'name = "life_disabled"\n'
        'type = "link_scan"\n'
        'enabled = false\n'
        'url = "https://blocked.org/jobs"\n'
        "link_pattern = 'blocked[.]org/jobs/[0-9]+$'\n",
        encoding="utf-8",
    )
    return path


def response(status: int, html: str = ""):
    return SimpleNamespace(status=status, ok=status == 200, text=html,
                           error="" if status == 200 else "blocked or inaccessible")


class Client:
    def __init__(self, answers: dict[str, object]):
        self.answers = answers
        self.requests: list[str] = []

    def get(self, url: str, *, use_cache: bool = False):
        assert use_cache is False
        self.requests.append(url)
        if url not in self.answers:
            raise AssertionError(f"Unexpected request to {url}")
        return self.answers[url]


def test_narrow_named_selection_does_not_request_unrelated_provider(tmp_path):
    client = Client({
        "https://example.org/search?q=epi": response(200, "<p>No jobs this cycle</p>"),
        "https://example.org/search?q=genomics": response(200, "<p>No jobs</p>"),
    })
    report = check_sources(
        client, catalogue(tmp_path), names={"life_euraxess"}, limit=1,
        detail_sample_limit=0,
    )
    assert report["checked"] == 1
    assert list(report["sources"]) == ["life_euraxess"]
    assert report["requested_names"] == ["life_euraxess"]
    assert client.requests == [
        "https://example.org/search?q=epi",
        "https://example.org/search?q=genomics",
    ]


def test_sampled_vacancy_details_use_robots_aware_client_and_report_denial(tmp_path):
    markup = "<a href='/jobs/123'>PhD</a><a href='/jobs/456'>Doctoral</a>"
    client = Client({
        "https://example.org/search?q=epi": response(200, markup),
        "https://example.org/search?q=genomics": response(200, markup),
        "https://example.org/jobs/123": response(999),
        "https://example.org/jobs/456": response(403),
    })
    report = check_sources(
        client, catalogue(tmp_path), names={"life_euraxess"},
        limit=1, detail_sample_limit=2,
    )
    item = report["sources"]["life_euraxess"]
    assert item["status"] == "ok"  # index remains accessible; details fail
    assert item["vacancy_links"] == 2
    assert item["detail_probe"] == {
        "same_origin_candidates": 2,
        "sampled": 2,
        "statuses": {"blocked_robots": 1, "http_error": 1},
        "http_status_counts": {"403": 1, "999": 1},
    }
    assert client.requests[-2:] == ["https://example.org/jobs/123",
                                    "https://example.org/jobs/456"]
    # Never print sampled application URLs, titles or user data in diagnostics.
    assert "/jobs/123" not in str(item["detail_probe"])
    assert "/jobs/456" not in str(item["detail_probe"])


def test_cross_origin_lookalike_url_must_not_trigger_detail_fetch(tmp_path):
    markup = (
        "<a href='/jobs/123'>Allowed detail</a>"
        "<a href='https://evil.org/redirect/example.org/jobs/999'>Spoofed</a>"
    )
    client = Client({
        "https://example.org/search?q=epi": response(200, markup),
        "https://example.org/search?q=genomics": response(200, markup),
        "https://example.org/jobs/123": response(200, "<html>Job detail</html>"),
    })
    report = check_sources(client, catalogue(tmp_path), names={"life_euraxess"},
                           limit=1, detail_sample_limit=2)
    item = report["sources"]["life_euraxess"]
    assert item["detail_probe"]["same_origin_candidates"] == 1
    assert item["detail_probe"]["sampled"] == 1
    assert item["detail_probe"]["statuses"] == {"ok": 1}
    assert all("evil.org" not in url for url in client.requests)


@pytest.mark.parametrize("names", [{"life_disabled"}, {"unknown"}, set(),
                                     {"life_euraxess", "life_unrelated", "third", "fourth"}])
def test_unsafe_named_source_selection_fails_before_network(tmp_path, names):
    client = Client({})
    with pytest.raises(ValueError):
        check_sources(client, catalogue(tmp_path), names=names, limit=3)
    assert client.requests == []


@pytest.mark.parametrize("sample_limit", [-1, 3, 20])
def test_unbounded_detail_sample_rejected_before_any_fetch(tmp_path, sample_limit):
    client = Client({})
    with pytest.raises(ValueError, match="detail_sample_limit"):
        check_sources(client, catalogue(tmp_path), names={"life_euraxess"},
                      detail_sample_limit=sample_limit)
    assert client.requests == []


def test_named_selection_must_not_skip_requested_source_via_offset(tmp_path):
    client = Client({})
    with pytest.raises(ValueError):
        check_sources(client, catalogue(tmp_path), names={"life_euraxess"},
                      offset=1, limit=1)
    assert client.requests == []
