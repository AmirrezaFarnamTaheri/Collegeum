"""Protect Life Sciences PhD alerts from economic-field false positives."""
from datetime import date

from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.ingest.life_sciences import classify_post


def _post(title: str) -> JobPostSchema:
    return JobPostSchema(
        title=title,
        url="https://www.mpg.de/27057371/phd-researcher-economic-impacts",
        source="life_max_planck",
        institution="Max Planck Society",
        country="Germany",
        location="Germany",
        description_snippet=(
            "The institute hosts genomics and neurobiology groups. "
            "Separate economic climate research is also conducted here."
        ),
    )


def test_economic_climate_phd_does_not_inherit_biology_from_employer_boilerplate():
    post = _post("PhD Researcher (m/f/d): Economic Impacts from Complex Climate Risks")
    assert classify_post(post, today=date(2026, 10, 29)) is None


def test_actual_biological_phd_still_qualifies_with_economic_secondary_subject():
    post = _post("PhD position in Molecular Biology and Economic Analysis of Biomanufacturing")
    assert classify_post(post, today=date(2026, 10, 29)) is not None
