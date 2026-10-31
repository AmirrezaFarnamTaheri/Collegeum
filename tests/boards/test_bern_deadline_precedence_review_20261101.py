"""Bern employer instructions must prevail over recruitment-index dates.

Red regressions for PR #97, based on the separately verified Bern adverts.
No network, production journals or subscriber receipts are accessed.
"""
from __future__ import annotations

from datetime import date

from predoc_pipeline.ingest.life_sciences import classify_post
from tests.boards.test_bern_employer_advert_verification_20261031 import (
    CANCER,
    GENESIS_WET,
    TRANSLATIONAL,
    _parse,
)


def test_employer_hard_deadline_prevails_over_conflicting_index_end_date() -> None:
    post = _parse(
        TRANSLATIONAL,
        title="PhD Student in Translational Cancer Research, SNSF project",
        ends="2026-11-21T22:59:59Z",
        application="Applications close on 15 November 2026.",
    )
    assert post.deadline == date(2026, 11, 15)
    assert post.extra["prospective_unverified_end_date"] == "2026-11-21T22:59:59Z"
    assert post.extra["prospective_employer_deadline_verified"] is True
    assert post.deadline_text and "employer" in post.deadline_text.lower()
    matched = classify_post(post, today=date(2026, 11, 1))
    assert matched is not None
    assert matched["deadline"] == "2026-11-15"
    assert matched["key"].startswith("career:")


def test_employer_hard_deadline_is_usable_when_index_has_no_end_date() -> None:
    post = _parse(
        TRANSLATIONAL,
        title="PhD Student in Translational Cancer Research, SNSF project",
        ends=None,
        application="Applications close on 15 November 2026.",
    )
    assert post.deadline == date(2026, 11, 15)
    assert post.extra["prospective_employer_deadline_verified"] is True
    assert "prospective_unverified_end_date" not in post.extra
    assert classify_post(post, today=date(2026, 11, 1))


def test_priority_review_for_full_consideration_is_not_a_hard_cutoff() -> None:
    post = _parse(
        TRANSLATIONAL,
        title="PhD Student in Translational Cancer Research, SNSF project",
        ends="2026-11-30T22:59:59Z",
        application=(
            "Apply by 30 November 2026 for full consideration. "
            "Applications received after this date may still be considered."
        ),
    )
    assert post.deadline is None
    assert post.extra["prospective_unverified_end_date"] == "2026-11-30T22:59:59Z"
    assert post.deadline_text and "review" in post.deadline_text.lower()
    assert classify_post(post, today=date(2026, 11, 1)) is None


def test_uncorroborated_and_rolling_index_dates_remain_unverified() -> None:
    no_cutoff = _parse(
        CANCER,
        title="PhD Student in Cancer Immunology and Leukemia Stem Cell Biology",
        ends="2026-11-27T22:59:59Z",
        application="Email your CV and letters of reference to the PI.",
    )
    assert no_cutoff.deadline is None
    assert "prospective_employer_deadline_verified" not in no_cutoff.extra
    rolling = _parse(
        GENESIS_WET,
        title="PhD position NCCR Genesis: combining remote and in-situ life detection techniques",
        ends="2026-12-31T22:59:59Z",
        application=(
            "The review of applications begins immediately and continues "
            "until the position is filled."
        ),
    )
    assert rolling.deadline is None
    assert rolling.deadline_text == "Rolling until filled"
    assert "prospective_employer_deadline_verified" not in rolling.extra
