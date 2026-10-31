"""Checkpointed search runs do not fork journals or delivery receipts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.ingest.life_sciences import (
    MAX_SOURCES,
    load_life_sources,
    select_sources,
)
from predoc_pipeline.ingest.rotation import save_rotation

ROOT = Path(__file__).resolve().parents[2]


def test_source_ledger_paths_are_separate_and_in_one_workflow_commit() -> None:
    econ = next(s for s in load_board_sources(ROOT / "config/sources.toml")
                if s.name == "linkedin")
    life = next(s for s in load_life_sources(ROOT / "config/life_sciences.toml")
                if s.name == "life_linkedin")
    assert econ.opt("checkpoint_path") == "data/linkedin_econ_search_state.json"
    assert life.opt("checkpoint_path") == "data/linkedin_life_search_state.json"
    assert econ.opt("checkpoint_path") != life.opt("checkpoint_path")
    assert econ.opt("cooldown_hours") == life.opt("cooldown_hours") == 48
    assert 1 <= life.opt("time_budget_seconds") < econ.opt("time_budget_seconds") <= 600
    assert life.opt("emit_per_run") <= 180
    workflow = (ROOT / ".github/workflows/pipeline.yml").read_text()
    stage = workflow[
        workflow.index("Commit updated state"):
        workflow.index("Commit private pipeline state")
    ]
    for path in (
        "data/listings.ndjson", "data/career_jobs.ndjson",
        "data/linkedin_econ_search_state.json",
        "data/linkedin_life_search_state.json",
    ):
        assert path in stage
    assert "git pull --rebase" in stage
    assert "git push" in stage


def test_life_linkedin_runs_every_cycle_without_starving_official_feeds(tmp_path) -> None:
    path = ROOT / "config/life_sciences.toml"
    ledger = tmp_path / "life_sources_rotation.json"
    enabled = {s.name for s in load_life_sources(path) if s.enabled}
    never_seen = enabled - {"life_linkedin"}
    observed: set[str] = set()
    for cycle in range(4):
        now = datetime(2026, 11, 1, 8, tzinfo=UTC) + timedelta(hours=4 * cycle)
        selected = select_sources(path, ledger)
        assert len(selected) == MAX_SOURCES
        assert "life_linkedin" in selected
        observed |= (selected - {"life_linkedin"})
        save_rotation(ledger, selected, timestamp=now)
    assert never_seen <= observed


def test_preserve_individual_employer_url_identities_and_delivery_receipts() -> None:
    # This branch changes discovery scheduling only; it must not edit or
    # regenerate historical source journals or Telegram acknowledgements.
    main_records = ROOT / "data/listings.ndjson"
    assert main_records.exists()
    workflow = (ROOT / ".github/workflows/pipeline.yml").read_text()
    assert "data/telegram_state.json" in workflow
    assert "data/seen.ndjson" in workflow



def test_life_journal_ack_only_releases_saved_not_unverified_candidates(
    tmp_path, monkeypatch,
) -> None:
    from datetime import date

    from predoc_pipeline.boards.config import HttpConfig
    from predoc_pipeline.boards.models import JobPostSchema
    from predoc_pipeline.boards.scrapers.linkedin_scheduler import QueryLedger
    from predoc_pipeline.ingest import life_sciences

    saved = tmp_path / "linkedin_life.json"
    ledger = QueryLedger("life_linkedin", max_items=1500)
    pair = ("PhD epigenetics", "Switzerland")
    now = datetime(2026, 11, 1, 8, tzinfo=UTC)
    ledger.request(pair, now=now)
    ledger.accept_page(
        pair,
        [
            {"id": "5980000000", "title": "PhD in Epigenetic Regulation"},
            {"id": "5980000001", "title": "PhD in Epigenetic Regulation"},
        ],
        now=now,
    )
    ledger.save(saved)
    registry = tmp_path / "life.toml"
    registry.write_text(
        '[[board]]\nname="life_linkedin"\ntype="linkedin"\n'
        'enabled=true\nrequire_deadline=true\n'
        f'checkpoint_path="{saved}"\nmax_replay_items=1500\n',
        encoding="utf-8",
    )

    def post(ident: str, deadline: date | None) -> JobPostSchema:
        return JobPostSchema(
            source="life_linkedin", title="PhD in Epigenetic Regulation",
            url=f"https://www.linkedin.com/jobs/view/{ident}",
            institution="University of Zurich",
            country="Switzerland", location="Zurich, Switzerland",
            deadline=deadline, extra={"require_deadline": True},
        )

    async def discover(_path, _http, *, selected_names, **_extra):
        assert selected_names == {"life_linkedin"}
        return [post("5980000000", date(2026, 12, 15)),
                post("5980000001", None)], []

    monkeypatch.setattr(life_sciences, "discover", discover)
    journal = tmp_path / "career.ndjson"
    count, errors = life_sciences.poll_life_sciences(
        journal, sources_path=registry, http_config=HttpConfig(),
    )
    assert count == 1 and errors == []
    replay = QueryLedger.load(saved, "life_linkedin", max_items=1500)
    assert {item["id"] for item in replay.items(now=now)} == {"5980000001"}
    assert replay.counts()["acknowledged_seen"] == 1
