"""Production Life Sciences health must not confuse empty, broken and live sources."""
from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from predoc_pipeline.boards.config import HttpConfig
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.ingest import life_sciences


class HttpContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


def _config(tmp_path):
    path = tmp_path / "life_sciences.toml"
    path.write_text(
        "".join(
            '[[board]]\nname="life_' + name + '"\ntype="link_scan"\n'
            'url="https://example.org/jobs"\nlink_pattern="example.org/job/"\n'
            + ('verified_empty_marker="No open PhD positions"\n' if name == "confirmed_empty" else "")
            for name in ("live", "uncertain_empty", "confirmed_empty", "partial", "failed")
        ),
        encoding="utf-8",
    )
    return path


def _posting(source: str) -> JobPostSchema:
    return JobPostSchema(
        title="PhD Position in Epigenetics", source=source,
        url=f"https://example.org/job/{source}", institution="University",
        country="Netherlands", description_snippet="epigenetics gene regulation",
    )


def test_discovery_records_per_source_outcomes_without_false_healthy_empty(
    tmp_path, monkeypatch,
):
    config = _config(tmp_path)

    class Scraper:
        def __init__(self, cfg, _http):
            self.cfg = cfg
            self.name = cfg.name
            self.discovery_fetch_errors = []
            self.discovery_parse_errors = []
            self.discovery_limits = []
            self.verified_empty_evidence = cfg.name.endswith('_confirmed_empty')

        async def run(self):
            if self.name.endswith("_failed"):
                raise RuntimeError("upstream unavailable")
            if self.name.endswith("_partial"):
                self.discovery_fetch_errors.append("incomplete query page")
            if self.name.endswith("_live") or self.name.endswith("_partial"):
                return [_posting(self.name)], 1
            return [], 0

        async def fetch_detail(self, _item):
            return ""

    monkeypatch.setattr(life_sciences, "SCRAPERS", {"link_scan": Scraper})
    monkeypatch.setattr(life_sciences, "build_http", lambda _cfg: HttpContext())
    outcomes = {}
    posts, errors = asyncio.run(
        life_sciences.discover(config, HttpConfig(), diagnostics=outcomes)
    )
    assert len(posts) == 2
    assert len(errors) == 2
    assert outcomes["life_live"]["status"] == "discovered"
    assert outcomes["life_live"]["doctoral_candidates"] == 1
    assert outcomes["life_uncertain_empty"]["status"] == "unverified_empty"
    assert outcomes["life_confirmed_empty"]["status"] == "verified_empty"
    assert outcomes["life_partial"]["status"] == "partial"
    assert outcomes["life_failed"]["status"] == "failed"
    assert outcomes["life_failed"]["vacancy_links"] == 0
    assert all(entry["matched_candidates"] == 0 for entry in outcomes.values())


def test_health_journal_preserves_prior_outcomes_when_other_sources_rotate(
    tmp_path, monkeypatch,
):
    from predoc_pipeline.ingest.life_health import read_life_health

    config = tmp_path / "life_sciences.toml"
    config.write_text(
        '[[board]]\nname="life_a"\ntype="link_scan"\nurl="https://example.org"\n'
        '[[board]]\nname="life_b"\ntype="link_scan"\nurl="https://example.org"\n',
        encoding="utf-8",
    )
    health = tmp_path / "life-health.json"
    journal = tmp_path / "career.ndjson"

    def first_discovery(_source, _http, *, selected_names, diagnostics):
        async def result():
            diagnostics["life_a"] = {
                "status": "discovered", "vacancy_links": 1,
                "doctoral_candidates": 1, "matched_candidates": 0,
                "discovery_issues": 0, "detail_failures": 0,
            }
            return [_posting("life_a")], []
        return result()

    monkeypatch.setattr(life_sciences, "select_sources", lambda *_: {"life_a"})
    monkeypatch.setattr(life_sciences, "discover", first_discovery)
    count, errors = life_sciences.poll_life_sciences(
        journal, sources_path=config, http_config=HttpConfig(), health_path=health,
    )
    assert (count, errors) == (1, [])
    initial = read_life_health(health)
    assert initial["sources"]["life_a"]["matched_candidates"] == 1
    assert initial["sources"]["life_a"]["status"] == "discovered"
    assert initial["sources"]["life_a"]["last_success_at"]

    def second_discovery(_source, _http, *, selected_names, diagnostics):
        async def result():
            diagnostics["life_b"] = {
                "status": "unverified_empty", "vacancy_links": 0,
                "doctoral_candidates": 0, "matched_candidates": 0,
                "discovery_issues": 0, "detail_failures": 0,
            }
            return [], []
        return result()

    monkeypatch.setattr(life_sciences, "select_sources", lambda *_: {"life_b"})
    monkeypatch.setattr(life_sciences, "discover", second_discovery)
    count, errors = life_sciences.poll_life_sciences(
        journal, sources_path=config, http_config=HttpConfig(), health_path=health,
    )
    assert (count, errors) == (0, [])
    updated = read_life_health(health)
    assert (updated["sources"]["life_a"]["last_success_at"]
            == initial["sources"]["life_a"]["last_success_at"])
    assert updated["sources"]["life_b"]["status"] == "unverified_empty"
    assert updated["checked_this_run"] == 1
    assert updated["catalogue"]["enabled"] == 2
    assert updated["catalogue"]["total"] == 2
    assert len(json.loads(health.read_text("utf-8"))["sources"]) == 2


def test_closed_cohort_call_requires_a_fresh_advertised_deadline():
    post = _posting("life_vib")
    post.title = "International PhD Call in Epigenetics"
    post.deadline = None
    assert life_sciences.classify_post(post, today=date(2026, 10, 30)) is None
    post.deadline = date(2026, 11, 22)
    assert life_sciences.classify_post(post, today=date(2026, 10, 30)) is not None
    assert life_sciences.classify_post(post, today=date(2026, 11, 23)) is None


def test_phd_required_by_applicant_excludes_mislabeled_doctoral_positions():
    candidate = _posting("life_vib")
    candidate.description_snippet = (
        "Qualifications: Applicants must already hold a completed PhD degree "
        "in molecular biology. Gene regulation."
    )
    assert life_sciences.classify_post(candidate, today=date(2026, 10, 30)) is None

    candidate.description_snippet = (
        "Work with postdoctoral fellows. Applicants need a master's degree "
        "in molecular biology; the advertised role is to complete a PhD."
    )
    assert life_sciences.classify_post(candidate, today=date(2026, 10, 30)) is not None
