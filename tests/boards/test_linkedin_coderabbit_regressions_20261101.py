"""Regressions for actionable CodeRabbit findings on PR #98.

No network access: only deterministic scheduler, filter, and persistence fixtures.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources, load_preferences
from predoc_pipeline.boards.filter import (
    RelevanceFilter,
    _econ_doctoral_admission_title,
)
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.boards.scrapers.linkedin_scheduler import QueryLedger
from predoc_pipeline.ingest.life_sciences import classify_post_decision

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 11, 1, 8, tzinfo=UTC)
CORE = ("PhD economics", "Germany")
OTHER = ("predoc economics", "France")
EXTRA = ("PhD finance", "Switzerland")


def _card(ident: str) -> dict[str, str]:
    return {"id": ident, "title": "PhD in Economics"}


def test_due_core_searches_have_priority_without_bypassing_48h_cooldown() -> None:
    ledger = QueryLedger("linkedin")
    picked = ledger.plan(
        [OTHER, EXTRA, CORE], core_pairs=[CORE], now=T0, limit=2,
    )
    assert CORE in picked
    ledger.request(CORE, now=T0)
    ledger.accept_page(CORE, [], now=T0)
    next_four_hours = ledger.plan(
        [OTHER, EXTRA, CORE], core_pairs=[CORE],
        now=T0 + timedelta(hours=4), limit=2,
    )
    assert CORE not in next_four_hours
    assert set(next_four_hours) == {OTHER, EXTRA}
    assert CORE in ledger.plan(
        [OTHER, EXTRA, CORE], core_pairs=[CORE],
        now=T0 + timedelta(hours=48), limit=2,
    )


def test_configured_core_phrases_are_reachable_without_special_repetition() -> None:
    cfg = next(
        s for s in load_board_sources(ROOT / "config/sources.toml")
        if s.name == "linkedin"
    )
    assert cfg.opt("verified") is False
    core = [(x["keyword"], x["location"]) for x in cfg.opt("core_queries")]
    pairs = [(kw, loc) for kw in cfg.opt("keywords") for loc in cfg.opt("locations")]
    scheduled = QueryLedger("linkedin").plan(
        pairs, core_pairs=core, now=T0, limit=cfg.opt("query_budget"),
    )
    assert set(core) <= set(scheduled)


def test_economics_phd_required_employment_is_not_an_admissions_title() -> None:
    assert _econ_doctoral_admission_title("Economics PhD programme")
    assert _econ_doctoral_admission_title("Econometrics PhD studentship")
    assert _econ_doctoral_admission_title("PhD in Economics")
    for title in (
        "Economics PhD required for senior research associate",
        "Economics PhD preferred for research economist",
        "Econometrics PhD required",
    ):
        assert not _econ_doctoral_admission_title(title), title
    filt = RelevanceFilter(
        load_preferences(ROOT / "config/preferences.toml").filters,
    )
    post = JobPostSchema(
        title="Economics PhD required for senior research associate",
        url="https://www.linkedin.com/jobs/view/4980000000",
        source="linkedin", institution="University of Oxford",
        location="Oxford, United Kingdom",
    )
    assert not filt.evaluate(post).keep


def test_replay_batch_fills_remaining_capacity_with_oldest_replays() -> None:
    ledger = QueryLedger("linkedin")
    ledger.request(CORE, now=T0)
    ledger.accept_page(CORE, [_card(str(4980000000 + i)) for i in range(3)], now=T0)
    first = {x["id"] for x in ledger.items(now=T0, limit=3)}
    assert len(first) == 3
    t1 = T0 + timedelta(hours=4)
    ledger.request(OTHER, now=t1)
    ledger.accept_page(OTHER, [_card("4980000003")], now=t1)
    second = ledger.items(now=t1, limit=3)
    assert len(second) == 3
    assert second[0]["id"] == "4980000003"
    assert len({x["id"] for x in second} & first) == 2


def test_life_science_classification_distinguishes_hard_and_soft_rejection() -> None:
    base = dict(
        source="life_linkedin", institution="University of Basel",
        url="https://www.linkedin.com/jobs/view/4980000011",
        title="PhD position in Epigenetics",
        country="Switzerland", location="Basel, Switzerland",
        extra={"require_deadline": True},
    )
    good = JobPostSchema(**base, deadline=date(2026, 12, 15))
    assert classify_post_decision(good, today=T0.date())[0] is not None
    missing = JobPostSchema(**base)
    assert classify_post_decision(missing, today=T0.date())[1] == "missing_deadline"
    wrong_field = JobPostSchema(
        **{**base, "title": "PhD position in Economics"},
        deadline=date(2026, 12, 15),
    )
    assert classify_post_decision(wrong_field, today=T0.date())[1] == "out_of_scope_title"
    wrong_country = JobPostSchema(
        **{**base, "country": "United States", "location": "New York, United States"},
        deadline=date(2026, 12, 15),
    )
    assert classify_post_decision(wrong_country, today=T0.date())[1] == "non_europe_location"
    wrong_role = JobPostSchema(
        **{**base, "title": "Postdoctoral Fellow in Epigenetics"},
        deadline=date(2026, 12, 15),
    )
    assert classify_post_decision(wrong_role, today=T0.date())[1] in (
        "not_doctoral", "wrong_role",
    )
