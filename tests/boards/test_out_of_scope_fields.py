"""Real employer-advert regressions: only relevant research fields should publish.

The two Copenhagen postings are distinct: pure mathematics is outside the
Collegeum scope, while statistics/insurance/economics is in scope. The
Cambridge digital-heritage role is archaeology, not social-science research.
"""
from __future__ import annotations

import pytest

from predoc_pipeline.boards.config import load_preferences
from predoc_pipeline.boards.filter import RelevanceFilter
from predoc_pipeline.boards.models import JobPostSchema

flt = RelevanceFilter(load_preferences("config/preferences.toml").filters)


@pytest.mark.parametrize(("title", "institution", "department"), [
    (
        "Research Assistant in Digital Heritage Documentation (Fixed Term)",
        "University of Cambridge - McDonald Institute for Archaeological Research",
        "McDonald Institute for Archaeological Research",
    ),
    (
        "Postdoctoral Positions in Mathematics",
        "University of Copenhagen",
        "Faculty of Science",
    ),
    (
        "Research Assistant in Archaeology",
        "University of Cambridge",
        "Department of Archaeology",
    ),
])
def test_unrelated_heritage_archaeology_and_pure_mathematics_are_rejected(
    title: str, institution: str, department: str
) -> None:
    post = JobPostSchema(
        title=title,
        institution=institution,
        department=department,
        source="jobs_ac_uk",
        url="https://example.org/vacancy/1",
    )
    verdict = flt.evaluate(post)
    assert not verdict.keep
    assert verdict.reason == "wrong-field"


@pytest.mark.parametrize(("title", "department"), [
    (
        "Postdoctoral Positions in Statistics and the Mathematics of Insurance and Economics",
        "Department of Mathematical Sciences",
    ),
    (
        "Postdoctoral Researcher in Mathematical Economics",
        "Department of Economics",
    ),
    (
        "Research Assistant in Archaeology and Public Policy",
        "Department of Public Policy",
    ),
])
def test_economics_and_policy_interdisciplinary_research_remains_eligible(
    title: str, department: str
) -> None:
    post = JobPostSchema(
        title=title,
        institution="University of Copenhagen",
        department=department,
        source="test",
        url="https://example.org/vacancy/2",
    )
    assert flt.evaluate(post).keep
