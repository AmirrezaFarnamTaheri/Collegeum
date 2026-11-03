"""Evidence-constrained, read-only official employer vacancy acceptance tests."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.probe_official_predoc_requisitions import probe_candidates

ROOT = Path(__file__).resolve().parents[2]
PRINCETON_INDEX = "https://rpde.princeton.edu/opportunities/jobs"
PRINCETON_JOB = (
    "https://research-princeton.icims.com/jobs/22348/"
    "senior-research-specialist/job?in_iframe=1"
)
BROOKINGS_INDEX = (
    "https://careers-brookings.icims.com/jobs/search?"
    "hashed=-435682078&ss=1"
)
BROOKINGS_JOB = (
    "https://careers-brookings.icims.com/jobs/3923/"
    "research-assistant%2C-economic-studies/job"
)


class Client:
    def __init__(self, results: dict[str, tuple[int, str]]):
        self.results = results
        self.calls: list[str] = []

    def get(self, url: str, *, use_cache: bool = False):
        assert not use_cache
        self.calls.append(url)
        status, html = self.results[url]
        return SimpleNamespace(ok=status == 200, status=status, text=html)


def fixture_client():
    return Client({
        PRINCETON_INDEX: (
            200, '<a href="' + PRINCETON_JOB + '">Senior Research Specialist</a>'
        ),
        PRINCETON_JOB: (
            200, '<html><h1>Senior Research Specialist</h1>'
                 '<p>Job ID 2026-22348</p></html>'
        ),
        BROOKINGS_INDEX: (
            200, '<a href="' + BROOKINGS_JOB +
                 '">Research Assistant Economic Studies</a>'
        ),
        BROOKINGS_JOB: (
            200, '<html><h1>Research Assistant Economic Studies</h1>'
                 '<p>Requisition 2026-3923</p></html>'
        ),
    })


def test_known_official_job_links_remain_unpublished_read_only_candidates():
    client = fixture_client()
    result = probe_candidates(client, ROOT / "config/sources.toml")
    assert client.calls == [
        PRINCETON_INDEX, PRINCETON_JOB, BROOKINGS_INDEX, BROOKINGS_JOB,
    ]
    assert result["request_budget"] == 4
    assert result["publishes_vacancies"] is False
    assert result["changes_source_configuration"] is False
    assert result["verified_open_positions"] == 0
    princeton = result["sources"]["princeton_rpde_jobs"]
    brookings = result["sources"]["brookings_jobs"]
    for row in (princeton, brookings):
        assert row["source_enabled"] is False
        assert row["index_status"] == "ok"
        assert row["detail_status"] == "ok"
        assert row["index_exact_requisition_link_observed"] is True
        assert row["requisition_label_visible_in_detail"] is True
        assert row["verified_open"] is False
    payload = json.dumps(result)
    assert "research-princeton.icims.com" not in payload
    assert "careers-brookings.icims.com" not in payload
    assert "Senior Research Specialist" not in payload


def test_403_and_robots_denial_do_not_get_labeled_empty_or_enabled():
    client = fixture_client()
    client.results[PRINCETON_INDEX] = (403, "Forbidden")
    client.results[BROOKINGS_JOB] = (999, "")
    result = probe_candidates(client, ROOT / "config/sources.toml")
    assert result["sources"]["princeton_rpde_jobs"]["index_status"] == "http_error"
    assert result["sources"]["brookings_jobs"]["detail_status"] == "blocked_robots"
    assert result["verified_open_positions"] == 0


def test_js_shell_without_vacancy_anchor_is_not_verified_empty():
    client = fixture_client()
    client.results[BROOKINGS_INDEX] = (
        200, '<html><h1>Search Results Page</h1><div id="app"></div></html>',
    )
    result = probe_candidates(client, ROOT / "config/sources.toml")
    row = result["sources"]["brookings_jobs"]
    assert row["index_status"] == "unverified_empty"
    assert row["index_exact_requisition_link_observed"] is False


def test_registry_drift_fails_before_any_provider_requests(tmp_path: Path):
    registry = tmp_path / "sources.toml"
    registry.write_text(
        '[[board]]\nname = "princeton_rpde_jobs"\ntype = "link_scan"\n'
        'enabled = true\nurl = "https://rpde.princeton.edu/opportunities/jobs"\n'
    )
    client = fixture_client()
    with pytest.raises(ValueError):
        probe_candidates(client, registry)
    assert not client.calls


def test_probe_workflow_is_main_only_and_makes_no_publication():
    workflow = (
        ROOT / ".github/workflows/verify-official-predoc-requisitions.yml"
    ).read_text()
    assert "refs/heads/main" in workflow
    assert "tools/probe_official_predoc_requisitions.py" in workflow
    assert "contents: read" in workflow
    assert "predoc-pipeline" not in workflow
    assert "wrangler deploy" not in workflow
    assert "secrets." not in workflow
