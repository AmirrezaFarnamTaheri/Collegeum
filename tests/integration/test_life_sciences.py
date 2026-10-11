"""Life-sciences PhD collection is separate from economics/public job rules."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from predoc_pipeline.boards.config import HttpConfig, load_board_sources
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.ingest import life_sciences
from predoc_pipeline.ingest.career import load_career, save_career
from predoc_pipeline.publish.feedback import FeedbackStore, generate_key
from predoc_pipeline.publish.private_delivery import plan_batch
from predoc_pipeline.publish.subscriptions import matching, render_alert
from predoc_pipeline.settings import Settings

TODAY = date(2026, 10, 11)


def post(
    *, title: str = "PhD position in Epigenetics",
    field: str = "", country: str | None = "Netherlands",
    location: str | None = "Utrecht", description: str = "",
    deadline: date | None = None, date_posted: date | None = None,
) -> JobPostSchema:
    return JobPostSchema(
        title=title, url="https://www.academictransfer.com/en/12345/phd-epigenetics/",
        source="life_academictransfer", country=country, location=location,
        institution="Utrecht University", fields_of_research=field,
        description_snippet=description, deadline=deadline, date_posted=date_posted,
    )


@pytest.mark.parametrize("title", [
    "PhD position in Epigenetics",
    "Doctoral Researcher in Chromatin Remodeling",
    "Doctorant in Epigenetics and Gene Regulation",
    "Doktorand in Functional Genomics",
    "PhD Scholarship in Molecular Biology",
    "PhD candidate in Psychiatric Genetics",
    "Doctoral Student in RNA Biology",
])
def test_genuine_doctoral_life_sciences_roles_match(title: str) -> None:
    result = life_sciences.classify_post(post(title=title), today=TODAY)
    assert result is not None
    assert result["category"] == "life_sciences_phd"
    assert result["scope"] == ""
    assert result["funding_status"] == "unverified"


@pytest.mark.parametrize("title", [
    "Postdoctoral Fellow in Epigenetics",
    "Research Associate (PhD required) in Epigenetics",
    "PhD position in Economics",
    "Master of Science in Molecular Biology",
    "Professor in Chromatin Biology",
])
def test_unrelated_or_ineligible_positions_are_excluded(title: str) -> None:
    assert life_sciences.classify_post(post(title=title), today=TODAY) is None


@pytest.mark.parametrize("country,location", [
    ("United Kingdom", "London"),
    ("United States", "Cambridge, MA"),
    ("Canada", "Toronto"),
    ("Japan", "Tokyo"),
    ("Europe", "Remote"),
    (None, None),
])
def test_explicit_european_geography_is_required(
    country: str | None, location: str | None,
) -> None:
    assert life_sciences.classify_post(
        post(country=country, location=location), today=TODAY,
    ) is None


def test_posting_date_and_funding_restrictions() -> None:
    assert life_sciences.classify_post(
        post(deadline=date(2026, 10, 10)), today=TODAY,
    ) is None
    assert life_sciences.classify_post(
        post(date_posted=date(2026, 6, 1)), today=TODAY,
    ) is None
    assert life_sciences.classify_post(
        post(description="This is an explicitly self-funded PhD."),
        today=TODAY,
    ) is None
    top = life_sciences.classify_post(
        post(title="PhD Candidate in Epigenetic Regulation"), today=TODAY,
    )
    assert top is not None and top["research_priority"] == "focus"
    related = life_sciences.classify_post(
        post(title="PhD Student in Computational Biology"), today=TODAY,
    )
    assert related is not None and related["research_priority"] == "related"


def test_separate_life_sciences_source_registry_keeps_economics_sources() -> None:
    repo = Path(__file__).resolve().parents[2]
    new_sources = load_board_sources(repo / "config/life_sciences.toml")
    default_sources = load_board_sources(repo / "config/sources.toml")
    enabled = {row.name for row in new_sources if row.enabled}
    assert enabled == {"life_euraxess", "life_academictransfer", "life_max_planck"}
    assert {"life_embl", "life_eth_bsse", "life_epfl"}.issubset(
        {row.name for row in new_sources if not row.enabled}
    )
    assert "euraxess" in {row.name for row in default_sources}
    assert "academictransfer" in {row.name for row in default_sources}


def test_poll_persists_life_phd_without_damaging_existing_economics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = tmp_path / "career.ndjson"
    economics = {
        "key": "career:econ", "category": "data_analyst", "scope": "remote",
        "title": "Data Analyst", "url": "https://jobicy.com/jobs/data-analyst",
        "employer": "Example", "location": "Anywhere", "source": "Jobicy",
    }
    save_career(journal, [], [economics])

    async def fake_discover(_sources: object, _http: object):
        return [post(title="PhD Position in Gene Regulation")], []

    monkeypatch.setattr(life_sciences, "discover", fake_discover)
    count, errors = life_sciences.poll_life_sciences(
        journal, sources_path="ignored", http_config=HttpConfig(),
    )
    assert count == 1 and errors == []
    records = load_career(journal)
    assert len(records) == 2
    assert {r["category"] for r in records} == {
        "data_analyst", "life_sciences_phd",
    }
    life = next(r for r in records if r["category"] == "life_sciences_phd")
    assert life["scope"] == ""
    first_seen = life["first_seen_at"]
    assert life_sciences.poll_life_sciences(
        journal, sources_path="ignored", http_config=HttpConfig(),
    )[0] == 0
    assert next(r for r in load_career(journal) if r["category"] == "life_sciences_phd")[
        "first_seen_at"
    ] == first_seen


def test_private_delivery_reaches_life_sciences_subscriber_without_markets(
    tmp_path: Path,
) -> None:
    cfg = Settings(
        _env_file=None, telegram_bot_token="test",
        telegram_public_channel_id="", telegram_admin_chat_id="",
        feedback_encryption_key=generate_key(),
        feedback_path=str(tmp_path / "feedback.json"),
        telegram_state_path=str(tmp_path / "updates.json"),
        state_path=str(tmp_path / "journal.ndjson"),
        seen_state_path=str(tmp_path / "seen.ndjson"),
        db_path=str(tmp_path / "db.sqlite"),
        career_state_path=str(tmp_path / "career.ndjson"),
        dashboard_json=str(tmp_path / "docs/listings.json"),
        feed_path=str(tmp_path / "docs/feed.xml"),
    )
    store = FeedbackStore.from_settings(cfg)
    store.toggle_subscription(101, "topics", "life_sciences_phd")
    store.subscriber(101)["topics"]["life_sciences_phd"] = (
        datetime.now(UTC) - timedelta(hours=1)
    ).isoformat()
    store.save()
    job = life_sciences.classify_post(post(), today=TODAY)
    assert job is not None
    save_career(cfg.career_state_path, [], [job])
    member = store.subscriber(101)
    assert member is not None and member["scopes"] == {}
    assert len(matching(member, [], load_career(cfg.career_state_path))) == 1
    formatted = render_alert(job)
    assert "Life Sciences PhD" in formatted
    assert "Funding, salary and tuition are not verified" in formatted
    batch = tmp_path / "batch.json"
    assert plan_batch(cfg, path=batch) == 1
    rows = json.loads(batch.read_text("utf-8"))
    assert rows[0]["chat_id"] == "101"
    assert rows[0]["key"].startswith("career:")
    assert "Life Sciences PhD" in rows[0]["text"]


def test_other_users_do_not_receive_life_sciences_phds() -> None:
    job = {
        **life_sciences.classify_post(post(), today=TODAY),
        "first_seen_at": datetime.now(UTC).isoformat(),
    }
    before = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    economics_member = {"topics": {"phd": before}, "scopes": {}}
    life_member = {"topics": {"life_sciences_phd": before}, "scopes": {}}
    assert matching(economics_member, [], [job]) == []
    assert len(matching(life_member, [], [job])) == 1


def test_international_research_brand_does_not_imply_location() -> None:
    from predoc_pipeline.boards.models import JobPostSchema

    baseline = {
        "title": "PhD Position in Epigenetics",
        "url": "https://www.mpg.de/jobs/example",
        "source": "life_max_planck",
        "institution": "Max Planck Society",
    }
    ambiguous = JobPostSchema(
        **baseline, description_snippet="Collaborators at the University of Berlin.",
    )
    assert life_sciences.classify_post(ambiguous, today=TODAY) is None
    verified = JobPostSchema(
        **baseline, description_snippet="Location: Munich, Germany",
    )
    match = life_sciences.classify_post(verified, today=TODAY)
    assert match is not None
    assert match["location"] == "Germany"
    outside = JobPostSchema(
        **baseline, description_snippet="Work location: Cambridge, UK",
    )
    assert life_sciences.classify_post(outside, today=TODAY) is None


def test_primary_research_interests_rank_before_related_on_same_discovery() -> None:
    stamp = datetime.now(UTC).isoformat()
    related = life_sciences.classify_post(
        post(title="PhD Student in Computational Biology"), today=TODAY,
    )
    focus = life_sciences.classify_post(
        post(title="PhD Position in Epigenetic Regulation"), today=TODAY,
    )
    assert related is not None and focus is not None
    related = {**related, "key": "career:related", "first_seen_at": stamp}
    focus = {**focus, "key": "career:focus", "first_seen_at": stamp}
    member = {
        "topics": {"life_sciences_phd": (
            datetime.now(UTC) - timedelta(hours=1)
        ).isoformat()},
        "scopes": {},
    }
    ranked = matching(member, [], [related, focus])
    assert [job["key"] for job in ranked] == ["career:focus", "career:related"]
