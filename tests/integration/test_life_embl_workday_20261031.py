"""EMBL's official multi-country Workday feed must retain geographic provenance."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.ingest import life_sciences


def test_embl_uses_existing_workday_adapter_without_institutional_country_guess():
    root = Path(__file__).resolve().parents[2]
    config = load_board_sources(root / "config/life_sciences.toml")
    embl = next(source for source in config if source.name == "life_embl")
    assert embl.enabled is True
    assert embl.type == "workday"
    assert embl.opt("url") == (
        "https://embl.wd103.myworkdayjobs.com/en-US/EMBL"
    )
    assert embl.country is None
    assert embl.institution == "EMBL"
    assert embl.opt("require_deadline") is True
    assert embl.opt("max_pages") >= 3


def test_embl_uk_recruitment_never_inherits_a_german_employer_country():
    post = JobPostSchema(
        title="PhD Student in Molecular Genomics",
        url=("https://embl.wd103.myworkdayjobs.com/en-US/EMBL/job/"
             "Hinxton-Cambridgeshire/PhD-Student-in-Molecular-Genomics_JR9999"),
        source="life_embl", institution="EMBL",
        location="Hinxton, Cambridgeshire", country=None,
        description_snippet="Research in molecular biology and genomics.",
        deadline=date(2026, 11, 30),
    )
    assert life_sciences.classify_post(post, today=date(2026, 10, 31)) is None


def test_embl_heidelberg_dated_eligible_phd_keeps_precise_country():
    post = JobPostSchema(
        title="PhD Student in Molecular Genomics",
        url=("https://embl.wd103.myworkdayjobs.com/en-US/EMBL/job/"
             "Heidelberg/PhD-Student-in-Molecular-Genomics_JR9999"),
        source="life_embl", institution="EMBL",
        location="Heidelberg", country=None,
        description_snippet="Research in molecular biology and genomics.",
        deadline=date(2026, 11, 30),
    )
    result = life_sciences.classify_post(post, today=date(2026, 10, 31))
    assert result is not None
    assert result["country"] == "Germany"


def test_embl_visitor_fellowships_for_existing_phds_are_not_doctoral_entry():
    post = JobPostSchema(
        title="EMBL CPP Visitor fellowships for PhDs and Postdocs (closing 31.10.2026)",
        url=("https://embl.wd103.myworkdayjobs.com/en-US/EMBL/job/"
             "EMBL-CPP-Visitor-fellowships-for-PhDs-and-Postdocs-_JR4342"),
        source="life_embl", institution="EMBL", country=None,
        description_snippet="Visiting fellowship for PhD-holding postdoctoral researchers.",
    )
    assert life_sciences.classify_post(post, today=date(2026, 10, 31)) is None


def test_general_workday_source_is_supported_by_life_sciences_discovery():
    assert "workday" in life_sciences.SCRAPERS
