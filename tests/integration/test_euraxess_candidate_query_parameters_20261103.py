"""Read-only EURAXESS candidate query parameter acceptance: no invented identities."""
from __future__ import annotations

import json
from types import SimpleNamespace

from tools.probe_euraxess_query_parameters import compare_candidate_queries


def page(*ids: int, count: int) -> str:
    links = "".join(
        f'<article><a href="https://euraxess.ec.europa.eu/jobs/{id_}">'
        f'PhD researcher {id_}</a></article>' for id_ in ids
    )
    return f'<html><h2>Search results ({count})</h2>{links}</html>'


class Client:
    def __init__(self, answers: dict[str, tuple[int, str]]):
        self.answers = answers
        self.calls: list[str] = []

    def get(self, url: str, *, use_cache: bool = False):
        assert not use_cache
        self.calls.append(url)
        status, html = self.answers[url]
        return SimpleNamespace(status=status, ok=status == 200, text=html)


PREFIX = "https://euraxess.ec.europa.eu/jobs/search"


def test_alternative_official_form_fields_have_bounded_distinct_query_evidence():
    client = Client({
        f"{PREFIX}?keys=epigenetics": (200, page(101, count=15)),
        f"{PREFIX}?keys=genomics": (200, page(202, count=18)),
        f"{PREFIX}?keywords=epigenetics": (200, page(99, count=6600)),
        f"{PREFIX}?keywords=genomics": (200, page(99, count=6600)),
    })
    result = compare_candidate_queries(client)
    assert client.calls == list(client.answers)
    assert len(client.calls) == 4
    params = {v["parameter"]: v for v in result["parameters"]}
    assert params["keys"]["query_result_signal"] == "distinct_nonempty"
    assert params["keys"]["distinct_observed_link_urls"] == 2
    assert [v["declared_result_count"] for v in params["keys"]["observations"]] == [15, 18]
    assert params["keywords"]["query_result_signal"] == "identical_nonempty"
    assert params["keywords"]["distinct_observed_link_urls"] == 1
    serialized = json.dumps(result)
    for leaked in ["/jobs/101", "/jobs/202", "/jobs/99", "PhD researcher"]:
        assert leaked not in serialized


def test_repeated_results_cannot_be_certified_as_filtered():
    client = Client({
        f"{PREFIX}?keys=epigenetics": (200, page(21, count=6000)),
        f"{PREFIX}?keys=genomics": (200, page(21, count=6000)),
        f"{PREFIX}?keywords=epigenetics": (200, page(21, count=6000)),
        f"{PREFIX}?keywords=genomics": (200, page(21, count=6000)),
    })
    result = compare_candidate_queries(client)
    assert all(p["query_result_signal"] == "identical_nonempty"
               for p in result["parameters"])
    assert result["verified_server_side_filter"] is False


def test_denied_or_empty_results_cannot_prove_filter_support():
    client = Client({
        f"{PREFIX}?keys=epigenetics": (999, ""),
        f"{PREFIX}?keys=genomics": (200, page(21, count=6000)),
        f"{PREFIX}?keywords=epigenetics": (403, ""),
        f"{PREFIX}?keywords=genomics": (200, ""),
    })
    result = compare_candidate_queries(client)
    assert all(p["query_result_signal"] == "indeterminate"
               for p in result["parameters"])
    assert result["verified_server_side_filter"] is False
    assert result["parameters"][0]["observations"][0]["status"] == "blocked_robots"
    assert result["parameters"][1]["observations"][0]["status"] == "http_error"


def test_probe_refuses_to_follow_arbitrary_urls_or_extra_parameters():
    client = Client({})
    try:
        compare_candidate_queries(client, terms=("http://example.net", "genomics"))
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe term must fail before requests")
    assert client.calls == []


def test_official_get_keys_form_reflects_requested_search_value():
    from tools.probe_life_sciences_sources import search_page_evidence

    html = ('<form method="get"><input type="search" name="keys" '
            'value="epigenetics" placeholder="Field, subject, position, '
            'location, keyword"></form><h2>Search results (14)</h2>')
    result = search_page_evidence(html, f"{PREFIX}?keys=epigenetics")
    assert result["search_input_names"] == ["keys"]
    assert result["search_value_reflected"] is True
    assert result["declared_result_count"] == 14


def test_official_form_field_probe_is_main_only_and_does_not_deploy():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/probe-euraxess-search-parameters.yml").read_text()
    assert "refs/heads/main" in workflow
    assert "tools/probe_euraxess_query_parameters.py" in workflow
    assert "--output" in workflow
    assert "PYTHONPATH: src:." in workflow
    # Both EURAXESS read-only probes share one concurrency group, preventing
    # parallel same-origin request bursts across independent GitHub workflows.
    assert "collegeum-life-euraxess-readonly-probe" in workflow
    assert "wrangler deploy" not in workflow


def test_network_exception_on_one_official_query_never_claims_filter_coverage():
    client = Client({
        f"{PREFIX}?keys=epigenetics": (200, page(101, count=12)),
        f"{PREFIX}?keys=genomics": (200, page(202, count=14)),
        f"{PREFIX}?keywords=epigenetics": (200, page(303, count=16)),
        # Last request intentionally raises KeyError, representing a transport failure.
    })
    result = compare_candidate_queries(client)
    assert len(client.calls) == 4
    assert result["parameters"][0]["query_result_signal"] == "distinct_nonempty"
    assert result["parameters"][1]["query_result_signal"] == "indeterminate"
    assert result["parameters"][1]["observations"][1]["status"] == "http_error"
    assert result["verified_server_side_filter"] is False
