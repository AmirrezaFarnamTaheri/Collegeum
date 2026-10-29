"""Guard rails for disabled candidate registry and read-only expansion probes."""
import asyncio
import csv
import tomllib
from pathlib import Path

import pytest

from predoc_pipeline.boards.config import load_board_sources
from tools.probe_source_expansion import probe_candidates, read_candidates

MANIFEST = Path("config/source_expansion_20261029.csv")
REGISTRY = Path("config/sources.toml")


def test_candidate_manifest_is_unique_complete_and_disabled():
    records = read_candidates()
    assert len(records) == 30
    assert sum(r["type"] == "workday" for r in records) == 19
    assert sum(r["type"] == "link_scan" for r in records) == 11
    configs = load_board_sources(REGISTRY)
    assert len({s.name for s in configs}) == len(configs)
    by_name = {s.name: s for s in configs}
    for r in records:
        cfg = by_name[r["name"]]
        assert cfg.enabled is False
        assert cfg.type == r["type"]
        assert cfg.opt("url") == r["url"]
        assert cfg.field_implied is False
        assert cfg.opt("link_pattern") if cfg.type == "link_scan" else cfg.opt("search_terms")
        assert r["evidence_url"].startswith("https://")


@pytest.mark.parametrize("limit,offset", [(0, 0), (11, 0), (1, -1), (1, 31)])
def test_probe_refuses_unbounded_batches(limit, offset):
    with pytest.raises(ValueError, match="invalid bounded"):
        asyncio.run(probe_candidates(limit=limit, offset=offset))


def test_all_candidates_are_in_only_one_manifest_row():
    with MANIFEST.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len({r["name"] for r in rows})
    assert all(r["enabled"] == "false" for r in rows)


def test_candidate_toml_is_parseable_and_counted_as_disabled():
    with REGISTRY.open("rb") as f:
        registry = tomllib.load(f)
    assert sum(not s.get("enabled", True) for s in registry["board"]) >= 30
    assert all(s.get("enabled") is False for s in registry["board"]
               if s["name"] in {r["name"] for r in read_candidates()})
