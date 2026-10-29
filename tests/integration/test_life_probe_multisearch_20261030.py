"""Runner source-health must audit every bounded query URL, not just the first."""
from pathlib import Path
from types import SimpleNamespace

from tools.probe_life_sciences_sources import check_sources


def catalog(tmp_path: Path, urls: list[str]) -> Path:
    path = tmp_path / "life_sciences.toml"
    quoted = ", ".join('"' + u + '"' for u in urls)
    path.write_text(
        '[[board]]\nname = "life_multipage"\ntype = "link_scan"\n'
        'enabled = true\n'
        f'urls = [{quoted}]\n'
        'link_pattern = "example[.]org/jobs/[0-9]+"\n',
        encoding="utf-8",
    )
    return path


class Client:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def get(self, url, *, use_cache):
        assert use_cache is False
        self.calls.append(url)
        return self.results[url]


def response(status, body=""):
    return SimpleNamespace(status=status, text=body, ok=status == 200)


def test_all_query_urls_reported_and_source_is_partial_on_one_robots_denial(tmp_path):
    urls = [f"https://example.org/search?q={i}" for i in range(4)]
    client = Client({
        urls[0]: response(200, "<a href='/about'>About</a>"),
        urls[1]: response(200, "<a href='/jobs/123'>PhD in Epigenetics</a>"),
        urls[2]: response(999),  # respectful robots denial
        urls[3]: response(200, "<a href='/jobs/456'>PhD in Genomics</a>"),
    })
    report = check_sources(client, catalog(tmp_path, urls), limit=1)
    observed = report["sources"]["life_multipage"]
    assert client.calls == urls
    assert report["checked"] == 1
    assert observed["status"] == "partial"
    assert observed["vacancy_links"] == 2
    assert observed["urls_checked"] == 4
    assert [e["status"] for e in observed["endpoints"]] == [
        "no_recognized_vacancy_links", "ok", "blocked_robots", "ok",
    ]


def test_duplicate_vacancy_urls_are_deduped_across_search_partitions(tmp_path):
    urls = ["https://example.org/search?q=epi", "https://example.org/search?q=gene"]
    markup = "<a href='/jobs/123'>PhD in functional genomics</a>"
    client = Client({u: response(200, markup) for u in urls})
    report = check_sources(client, catalog(tmp_path, urls), limit=1)
    item = report["sources"]["life_multipage"]
    assert item["status"] == "ok"
    assert item["vacancy_links"] == 1
    assert [r["vacancy_links"] for r in item["endpoints"]] == [1, 1]


def test_http_error_on_one_endpoint_does_not_hide_other_valid_query(tmp_path):
    urls = ["https://example.org/search?q=one", "https://example.org/search?q=two"]
    client = Client({
        urls[0]: response(503),
        urls[1]: response(200, "<a href='/jobs/987'>PhD in Genomics</a>"),
    })
    item = check_sources(client, catalog(tmp_path, urls), limit=1)["sources"]["life_multipage"]
    assert item["status"] == "partial"
    assert item["vacancy_links"] == 1
    assert item["endpoints"][0]["http_status"] == 503


def test_more_than_four_urls_fails_closed_without_issuing_network(tmp_path):
    urls = [f"https://example.org/search?q={i}" for i in range(5)]
    client = Client({})
    item = check_sources(client, catalog(tmp_path, urls), limit=1)["sources"]["life_multipage"]
    assert item["status"] == "too_many_urls"
    assert client.calls == []
