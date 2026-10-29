"""Job workplace evidence outranks the crawler's country-of-institution hint."""
from datetime import date

import pytest

from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.ingest.life_sciences import classify_post


def _job(*, country: str, location: str, inferred_source_country: bool):
    return JobPostSchema(
        title="PhD position in Molecular Biology and Functional Genomics",
        url="https://example.org/jobs/doctoral-123",
        institution="European Research University",
        source="life_regional_university",
        country=country,
        location=location,
        extra={"source_country_default": inferred_source_country},
    )


@pytest.mark.parametrize("location", ["London, United Kingdom", "Toronto, Canada",
                                      "Cambridge, Massachusetts, United States"])
def test_european_institution_default_cannot_override_explicit_foreign_workplace(location):
    row = _job(country="Netherlands", location=location, inferred_source_country=True)
    assert classify_post(row, today=date(2026, 10, 29)) is None


def test_matching_local_workplace_stays_eligible():
    row = _job(country="Netherlands", location="Utrecht, Netherlands",
               inferred_source_country=True)
    match = classify_post(row, today=date(2026, 10, 29))
    assert match is not None
    assert match["country"] == "Netherlands"


def test_explicit_advert_country_is_not_overridden_by_an_ambiguous_city():
    row = _job(country="United Kingdom", location="Cambridge",
               inferred_source_country=False)
    assert classify_post(row, today=date(2026, 10, 29)) is None
