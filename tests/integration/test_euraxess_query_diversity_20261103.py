"""Regression for EURAXESS keyword-query drift: partial, not healthy discovery."""
from __future__ import annotations

import asyncio
from pathlib import Path

from predoc_pipeline.boards.config import HttpConfig
from predoc_pipeline.ingest import life_sciences


class HtmlClient:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.requested: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get_text(self, url: str) -> str:
        self.requested.append(url)
        return self.pages[url]


def _config(tmp_path: Path, *, guarded: bool = True) -> Path:
    path = tmp_path / "sources.toml"
    path.write_text(
        '[[board]]\n'
        'name = "life_filtered"\n'
        'type = "link_scan"\n'
        'enabled = true\n'
        'institution = "Example University"\n'
        'country = "Germany"\n'
        'urls = ["https://example.edu/search?q=epigenetics", '
        '"https://example.edu/search?q=genomics"]\n'
        "link_pattern = 'example[.]edu/jobs/[0-9]+$'\n"
        f"query_result_diversity_required = {str(guarded).lower()}\n",
        encoding="utf-8",
    )
    return path


def _markup(*ids: int) -> str:
    return "".join(
        f'<article><a href="https://example.edu/jobs/{value}">'
        "PhD Position in Functional Genomics</a></article>"
        for value in ids
    )


def _discover(tmp_path, monkeypatch, *, pages, guarded=True):
    client = HtmlClient(pages)
    monkeypatch.setattr(life_sciences, "build_http", lambda _cfg: client)
    monkeypatch.setattr(life_sciences, "_needs_detail", lambda _post: False)
    diagnostics = {}
    found, errors = asyncio.run(
        life_sciences.discover(
            _config(tmp_path, guarded=guarded),
            HttpConfig(timeout=3, max_retries=0),
            diagnostics=diagnostics,
        )
    )
    return found, errors, diagnostics["life_filtered"], client.requested


def test_same_two_keyword_queries_retain_candidates_but_mark_partial(tmp_path, monkeypatch):
    pages = {
        "https://example.edu/search?q=epigenetics": _markup(101, 202),
        "https://example.edu/search?q=genomics": _markup(202, 101),
    }
    posts, errors, status, requested = _discover(tmp_path, monkeypatch, pages=pages)
    assert len(posts) == 2
    assert {x.url for x in posts} == {
        "https://example.edu/jobs/101", "https://example.edu/jobs/202",
    }
    assert requested == list(pages)
    assert status["status"] == "partial"
    assert status["discovery_issues"] == 1
    # Discovery warnings intentionally contain only an aggregate count,
    # never job-specific URLs, upstream HTML or identifying position fields.
    assert errors == ["life_filtered: 1 discovery issues"]
    assert "/jobs/101" not in errors[0]


def test_changed_query_results_keep_healthy_status(tmp_path, monkeypatch):
    pages = {
        "https://example.edu/search?q=epigenetics": _markup(101),
        "https://example.edu/search?q=genomics": _markup(202),
    }
    posts, errors, status, _ = _discover(tmp_path, monkeypatch, pages=pages)
    assert len(posts) == 2
    assert errors == []
    assert status["status"] == "discovered"
    assert status["discovery_issues"] == 0


def test_identical_views_are_not_rejected_for_unflagged_university_source(
    tmp_path, monkeypatch,
):
    pages = {
        "https://example.edu/search?q=epigenetics": _markup(101),
        "https://example.edu/search?q=genomics": _markup(101),
    }
    posts, errors, status, _ = _discover(
        tmp_path, monkeypatch, pages=pages, guarded=False
    )
    assert len(posts) == 1
    assert status["status"] == "discovered"
    assert errors == []


def test_enabled_life_euraxess_keyword_shards_opt_in_without_disabling(tmp_path):
    from predoc_pipeline.ingest.life_sciences import load_life_sources

    root = Path(__file__).resolve().parents[2]
    configured = {s.name: s for s in load_life_sources(root / "config/life_sciences.toml")}
    names = ("life_euraxess", "life_euraxess_cell_models",
             "life_euraxess_computational")
    for name in names:
        source = configured[name]
        assert source.enabled is True
        assert source.opt("query_result_diversity_required") is True
        assert len(source.opt("urls")) >= 2
