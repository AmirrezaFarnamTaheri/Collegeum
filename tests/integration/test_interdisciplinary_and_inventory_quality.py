"""Regression contract: funded interdisciplinary PhDs and source-correct Predocs."""
import json
from pathlib import Path

import pytest

from predoc_pipeline.boards.config import Preferences
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.ingest.life_sciences import (
    classify_post,
    historical_life_title_disqualified,
)
from predoc_pipeline.models import Discipline, Location, PredocListing
from predoc_pipeline.routing import Channel, Router


def _listing(title, summary, *, country="Germany", degree="masters"):
    return PredocListing(
        title=title,
        institution="Example Research University",
        location=Location(country=country, city=None),
        disciplines=[Discipline.QUANT_SOCIAL],
        summary=summary,
        min_degree=degree,
        apply_url="https://example.edu/vacancy/123",
        source_url="https://example.edu/vacancy/123",
    )


def test_original_joint_hku_max_planck_studentship_qualifies_from_stored_record():
    rows = [
        json.loads(line) for line in
        (Path(__file__).resolve().parents[2] / "data/listings.ndjson")
        .read_text(encoding="utf-8").splitlines()
    ]
    item = next(row for row in rows if row["id"] == 195)
    job = _listing(
        item["title"], item["summary"],
        country=item["country"], degree=item["min_degree"],
    )
    assert job.location.country == "Hong Kong"
    assert Router(Preferences()).destinations(job) == frozenset({
        Channel.WEB, Channel.TELEGRAM,
    })


@pytest.mark.parametrize(("title", "summary"), [
    (
        "PhD Researcher in Computational Human Sciences",
        "Funded doctoral research on computational human sciences and migration.",
    ),
    (
        "Doctoral Candidate in Computational Social Science",
        "A doctoral research project studying online political behaviour through "
        "computational social science and network analysis.",
    ),
    (
        "Doctoral Researcher in Digital and Computational Demography",
        "The funded project studies population mobility and demographic change.",
    ),
    (
        "PhD Studentship in Population Health and Data Science",
        "A jointly funded four-year studentship researching population health "
        "and social data using quantitative methods.",
    ),
    (
        "PhD in Computer Science: Computational Social Science",
        "Research project in computational social science and civic networks.",
    ),
    (
        "PhD Candidate in Quantitative Social Sciences",
        "Doctoral research in comparative social inequalities with statistical data.",
    ),
    (
        "PhD Studentship in Population Studies",
        "This jointly funded studentship requires admission to two partner "
        "universities and carries a defined four-year research award.",
    ),
])
def test_genuine_interdisciplinary_doctoral_positions_qualify(title, summary):
    assert Router(Preferences()).destinations(
        _listing(title, summary)
    ) == frozenset({Channel.WEB, Channel.TELEGRAM})


@pytest.mark.parametrize(("title", "summary", "degree", "country"), [
    (
        "PhD in Economics: application to graduate degree programme",
        "General admissions to the economics PhD programme.",
        "masters", "Germany",
    ),
    (
        "PhD Studentship in Population Studies",
        "General admissions to a doctoral school. Funding may be available.",
        "masters", "Germany",
    ),
    (
        "PhD Candidate in Computer Science",
        "Research on compiler optimization and distributed systems.",
        "masters", "Germany",
    ),
    (
        "PhD Student in Molecular Genetics",
        "Fully funded four-year doctoral position in cellular genetics.",
        "masters", "Germany",
    ),
    (
        "PhD Candidate in Political Science",
        "Research on international relations and elite diplomacy.",
        "masters", "Germany",
    ),
    (
        "Postdoctoral Fellow in Computational Social Science",
        "This is a research appointment for an already qualified PhD.",
        "phd", "Germany",
    ),
    (
        "Doctoral Researcher in Demography",
        "Doctoral research on population projections.",
        "phd", "Germany",
    ),
    (
        "PhD Candidate in Demography",
        "Funded doctoral project studying population migration.",
        "masters", "United States",
    ),
])
def test_unrelated_or_qualified_staff_still_not_sent(title, summary, degree, country):
    assert Router(Preferences()).destinations(
        _listing(title, summary, country=country, degree=degree)
    ) == frozenset({Channel.WEB})


def test_official_colombia_predoc_workplace_not_us_headquarters():
    rows = [
        json.loads(line) for line in
        (Path(__file__).resolve().parents[2] / "data/listings.ndjson")
        .read_text(encoding="utf-8").splitlines()
    ]
    item = next(row for row in rows if row["id"] == 53)
    assert item["title"] == "Research Associate - Good Business Lab"
    assert item["country"] == "Colombia"
    assert item["is_remote"] is True
    assert item["source_url"].startswith("https://www.povertyactionlab.org/")
    # Original publication identity and receipts must not be reset.
    assert item["telegram_message_id"] is None


def test_hong_kong_predoc_has_explicit_country_but_keeps_legacy_receipt():
    rows = [
        json.loads(line) for line in
        (Path(__file__).resolve().parents[2] / "data/listings.ndjson")
        .read_text(encoding="utf-8").splitlines()
    ]
    item = next(row for row in rows if row["id"] == 40)
    assert item["country"] == "Hong Kong"
    assert item["telegram_message_id"] == 20


@pytest.mark.parametrize("title", [
    "PhD Position Improving Symbolic AI through Learning and Reasoning",
    "Upp till sex doktorandplatser i nationalekonomi",
    "PhD student in Computing Science with focus on Graph Transformations",
])
def test_out_of_scope_doctorates_cannot_linger_as_life_sciences(title):
    assert historical_life_title_disqualified(title)


def test_unrelated_symbolic_ai_phd_not_reclassified_from_university_boilerplate():
    post = JobPostSchema(
        title="PhD Position Improving Symbolic AI through Learning and Reasoning",
        url="https://example.edu/jobs/ai",
        source="life_euraxess",
        institution="Example University",
        country="Netherlands",
        location="Amsterdam",
        description_snippet="The university is famous for CRISPR and molecular biology.",
    )
    assert classify_post(post) is None


def test_biology_relevant_machine_learning_does_not_get_excluded():
    post = JobPostSchema(
        title="PhD Student in Machine Learning for Genome Regulation",
        url="https://example.edu/jobs/biology-ml",
        source="life_euraxess",
        institution="Example University",
        country="Netherlands",
        location="Amsterdam",
        description_snippet="PhD research in gene regulation and chromatin genomics.",
    )
    assert classify_post(post) is not None


def test_numeric_ats_location_falls_back_to_verified_country():
    post = JobPostSchema(
        title="PhD Candidate in Regulation of Liver Metabolism by miRNAs",
        url="https://example.edu/jobs/biomedical",
        source="life_special_de_helmholtz_munich",
        institution="Helmholtz Munich",
        country="Germany",
        location="7",
        description_snippet="Doctoral project in RNA biology and gene regulation.",
    )
    result = classify_post(post)
    assert result is not None
    assert result["location"] == "Germany"
