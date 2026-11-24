"""Quarantine official portals failing production and robots-aware runner checks."""
from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources

REGISTRY = Path("config/sources.toml")
QUARANTINED = {"crest_jobs", "copenhagen", "mannheim_econ"}
RETAIN = {
    "tamu_public_policy", "brandeis_business_econ",
    "urban_institute_policy", "federal_reserve_system_jobs",
    "nus_policy_research", "wifo_austria_jobs", "ceps_brussels_research",
}
REVIEWED_NOVEMBER = {"esmt_berlin_research", "isb_academic_research", "wu_vienna_research"}
REVIEWED_UNIVERSITIES = {
    "vienna_university_research", "amsterdam_university_research",
    "maastricht_university_research", "utrecht_university_research",
}


def test_robots_denied_providers_are_not_scheduled_as_healthy():
    boards = {source.name: source for source in load_board_sources(REGISTRY)}
    for name in QUARANTINED:
        assert boards[name].enabled is False
        assert "robots" in str(boards[name].opt("note", "")).lower()
    assert all(boards[name].enabled for name in RETAIN)


def test_ifau_joins_verified_empty_coverage_without_reenabling_failed_sources():
    boards = load_board_sources(REGISTRY)
    reviewed = REVIEWED_NOVEMBER | REVIEWED_UNIVERSITIES
    legacy = [source for source in boards if source.name not in reviewed]
    assert len(legacy) == 144
    # Mannheim remains disabled after a robots.txt denial. The Federal
    # Reserve Board navigation-only index is also disabled after its verified
    # internship guidance page was mispublished as a vacancy (listing 201).
    assert sum(source.enabled for source in legacy) == 75
    additions = [source for source in boards if source.name in REVIEWED_NOVEMBER]
    assert {source.name for source in additions} == REVIEWED_NOVEMBER
    assert all(source.enabled and source.type == "official_research"
               and not source.field_implied for source in additions)
    universities = [source for source in boards if source.name in REVIEWED_UNIVERSITIES]
    assert {source.name for source in universities} == REVIEWED_UNIVERSITIES
    assert all(source.enabled and source.type == "official_university"
               and not source.field_implied for source in universities)
    assert next(s for s in boards if s.name == "fed_board").enabled is False
    assert len({source.name for source in boards}) == len(boards) == 144 + len(reviewed)
