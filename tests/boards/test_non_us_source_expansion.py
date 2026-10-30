"""Non-US candidate manifest stays separate from activation and public outputs."""
from pathlib import Path

import pytest

from predoc_pipeline.boards.config import load_board_sources
from tools.probe_source_expansion import read_candidates

NON_US = Path("config/non_us_sources_20261029.csv")
REGISTRY = Path("config/sources.toml")


def test_non_us_manifest_has_21_distinct_disabled_sources():
    rows = read_candidates(NON_US)
    assert len(rows) == 21
    assert {r["type"] for r in rows} == {"link_scan"}
    assert len({r["name"] for r in rows}) == 21
    assert all(r["enabled"] == "false" for r in rows)
    assert all(r["country"] != "United States" for r in rows)


def test_non_us_candidates_have_no_implicit_economic_fields():
    rows = read_candidates(NON_US)
    board = {s.name: s for s in load_board_sources(REGISTRY)}
    for row in rows:
        cfg = board[row["name"]]
        assert cfg.enabled is (row["name"] in {
            "nus_policy_research", "wifo_austria_jobs",
            "ceps_brussels_research", "ifau_sweden_labour",
        })
        assert cfg.field_implied is False
        assert cfg.type == "link_scan"
        assert cfg.opt("url") == row["url"]
        assert cfg.opt("link_pattern").startswith("^")
        assert row["evidence_url"].startswith("https://")


def test_non_us_manifest_does_not_duplicate_initial_cohort():
    us_names = {row["name"] for row in read_candidates()}
    non_us_names = {row["name"] for row in read_candidates(NON_US)}
    assert us_names.isdisjoint(non_us_names)


@pytest.mark.parametrize("bad", [Path("config/sources.toml"), Path("foo.csv")])
def test_probe_rejects_unknown_manifests(bad):
    with pytest.raises(ValueError):
        read_candidates(bad)
