"""Only independently evidenced, narrowly-scoped employer boards may be promoted."""
import csv
import re
from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources
from tools.probe_source_expansion import NON_US_MANIFEST, read_candidates

ACTIVATIONS = Path("config/approved_research_sources_wave1_20261029.csv")
REGISTRY = Path("config/sources.toml")
WAVE2 = {"wifo_austria_jobs", "ceps_brussels_research", "ifau_sweden_labour"}
EXPECTED = {
    "tamu_public_policy": ("Predoctoral Research Assistant", "Postdoctoral Research Assistant"),
    "brandeis_business_econ": (
        "Temporary Research Assistant - School of Business and Economics 2026",
        "Research Administrative Assistant",
    ),
    "urban_institute_policy": (
        "Research Assistant – Quantitative (Health, Income, and Benefits Policy Division)",
        "Senior Research Fellow, Quantitative Policy",
    ),
    "federal_reserve_system_jobs": (
        "Research Assistant/Sr. Research Assistant",
        "Director of Economic Research",
    ),
    "nus_policy_research": (
        "Research Assistant (Policy Lab)", "Executive (Field Operations Management)",
    ),
}


def test_reviewed_wave_has_exactly_five_distinct_official_vacancy_evidence_urls():
    with ACTIVATIONS.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(EXPECTED) == len({r["name"] for r in rows})
    assert {r["name"] for r in rows} == set(EXPECTED)
    assert len({r["vacancy_evidence_url"] for r in rows}) == len(rows)
    assert all(r["vacancy_evidence_url"].startswith("https://") for r in rows)
    candidates = {r["name"] for r in read_candidates()}
    candidates |= {r["name"] for r in read_candidates(NON_US_MANIFEST)}
    assert set(EXPECTED).issubset(candidates)


def test_only_approved_candidate_sources_are_enabled_and_title_guarded():
    sources = {x.name: x for x in load_board_sources(REGISTRY)}
    candidates = {r["name"] for r in read_candidates()}
    candidates |= {r["name"] for r in read_candidates(NON_US_MANIFEST)}
    assert {x for x in candidates if sources[x].enabled} == (set(EXPECTED) | WAVE2)
    assert sources["yale_inclusion_economics"].enabled is False  # overlaps Yale EGC
    for name, (positive, negative) in EXPECTED.items():
        source = sources[name]
        assert source.enabled
        assert source.field_implied is False
        pattern = re.compile(source.opt("title_allow_pattern"), re.IGNORECASE)
        assert pattern.search(positive)
        assert not pattern.search(negative)


def test_non_us_promoted_source_is_singapore_only_without_implicit_fields():
    sources = {x.name: x for x in load_board_sources(REGISTRY)}
    source = sources["nus_policy_research"]
    assert source.country == "Singapore"
    assert source.type == "link_scan"
    assert source.opt("link_pattern").startswith("^https://")
    assert not source.field_implied
