"""Cross-source health must reflect the checked-out catalogues, not an old run snapshot."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tools.reconcile_public_health import (
    checkpoint,
    classify_snapshot,
    reconcile_health,
)

NOW = datetime(2026, 11, 21, 15, tzinfo=UTC)
COUNTS = {
    "total": 2, "successful": 1, "empty": 0, "failed": 1,
    "partial": 0, "skipped": 0,
}


def health():
    return {
        "generated_at": "2026-11-21T14:55:00Z", "status": "degraded",
        "last_run": {"run_id": "44915539651", "outcome": "partial",
                     "sources": COUNTS},
        "official_calls": {
            "generated_at": "2026-11-21T12:55:00Z",
            "empty_indexes": 3, "document_only_indexes": 0,
        },
    }


def test_independent_snapshot_freshness_rejects_challenges_and_future_clock():
    for stamp, expected in [
        ("2026-11-21T14:59:00Z", "current"),
        ("2026-11-21T04:59:00Z", "stale"),
        ("2026-11-21T15:07:00Z", "future"),
        ("2026-11-21T15:00:00", "invalid"),
        ("2026-not-a-date", "invalid"),
        (None, "missing"),
    ]:
        assert classify_snapshot(
            stamp, now=NOW, max_age=timedelta(hours=8),
        )["state"] == expected


def test_reconcile_old_report_after_rebase_preserves_application_and_receipts():
    old = health()
    report = {
        "generated_at": "2026-11-21T14:49:00Z", "status": "degraded",
        "empty_indexes": 1, "document_only_indexes": 2,
    }
    observed = {
        "official_calls": report["generated_at"],
        "phd_admissions": "2026-11-21T14:47:00Z",
        "life_sciences": "2026-11-21T14:50:00+00:00",
        "career": "2026-11-21T14:52:00+00:00",
        "listings": "2026-11-21T14:54:50Z",
    }
    result = reconcile_health(
        old, report, observed, expected_run_id="44915539651", now=NOW,
    )
    assert result["last_run"] == old["last_run"]
    assert result["generated_at"] == old["generated_at"]
    assert result["status"] == "degraded"
    assert result["official_calls"]["empty_indexes"] == 1
    assert result["official_calls"]["document_only_indexes"] == 2
    metadata = result["component_snapshots"]["official_calls"]
    assert metadata["previous_summary_generated_at"] == "2026-11-21T12:55:00Z"
    assert metadata["reconciled"] is True
    assert all(row["state"] == "current"
               for row in result["component_snapshots"].values())


def test_invalid_run_id_summary_and_false_green_fail_closed():
    old = health()
    with pytest.raises(ValueError, match="run"):
        reconcile_health(old, {}, {}, expected_run_id="different", now=NOW)
    with pytest.raises(ValueError, match="summary"):
        reconcile_health(
            {**old, "last_run": {**old["last_run"],
                                 "sources": {**COUNTS, "total": 3}}},
            {}, {}, expected_run_id="44915539651", now=NOW,
        )
    with pytest.raises(ValueError, match="application"):
        reconcile_health(
            {**old, "status": "ok"}, {}, {},
            expected_run_id="44915539651", now=NOW,
        )


def test_stale_missing_and_future_catalogues_never_claim_open_calls():
    old = health()
    for stamp, expected in [
        (None, "missing"), ("2026-11-21T15:07:00Z", "future"),
        ("2026-11-21T04:00:00Z", "stale"),
    ]:
        report = {"status": "ok", "eligible": 19, "unpublished": 10,
                  "generated_at": stamp}
        result = reconcile_health(
            old, report, {"official_calls": stamp},
            expected_run_id="44915539651", now=NOW,
        )
        assert result["component_snapshots"]["official_calls"]["state"] == expected
        assert result["official_calls"]["eligible"] is None
        assert result["official_calls"]["unpublished"] is None
        assert result["official_calls"]["status"] != "ok"


def test_mismatched_report_and_catalogue_never_claim_current():
    old = health()
    result = reconcile_health(
        old, {"status": "ok", "eligible": 2,
              "generated_at": "2026-11-21T12:55:00Z"},
        {"official_calls": "2026-11-21T14:49:00Z"},
        expected_run_id="44915539651", now=NOW,
    )
    assert result["component_snapshots"]["official_calls"]["state"] == "mismatched"
    assert result["official_calls"]["status"] == "unavailable"


def test_postcheckpoint_check_only_reads_valid_latest_snapshot(tmp_path):
    root = tmp_path
    (root / "docs/data").mkdir(parents=True)
    (root / "data").mkdir()
    for name, stamp_field, stamp in [
        ("docs/data/official_phd_calls.json", "generated_at", "2026-11-21T14:49:00Z"),
        ("docs/data/phd_admissions.json", "generated_at", "2026-11-21T14:47:00Z"),
        ("data/life_sources_health.json", "checked_at", "2026-11-21T14:50:00Z"),
        ("data/career_health.json", "checked_at", "2026-11-21T14:52:00Z"),
        ("docs/data/listings.json", "generated_at", "2026-11-21T14:55:00Z"),
    ]:
        target = root / name
        target.write_text(json.dumps({stamp_field: stamp}))
    report = {"generated_at": "2026-11-21T14:49:00Z",
              "status": "degraded", "eligible": 0}
    observed = {
        "official_calls": "2026-11-21T14:49:00Z",
        "phd_admissions": "2026-11-21T14:47:00Z",
        "life_sciences": "2026-11-21T14:50:00Z",
        "career": "2026-11-21T14:52:00Z",
        "listings": "2026-11-21T14:55:00Z",
    }
    safe = reconcile_health(
        health(), report, observed, expected_run_id="44915539651", now=NOW,
    )
    target = root / "docs/data/health.json"
    target.write_text(json.dumps(safe))
    before = target.read_bytes()
    assert checkpoint(
        root, expected_run_id="44915539651", now=NOW, write=False,
    )["status"] == "checked"
    assert target.read_bytes() == before
    # A later independently refreshed catalogue must invalidate old summary.
    (root / "docs/data/official_phd_calls.json").write_text(
        json.dumps({"generated_at": "2026-11-21T14:57:00Z"}),
    )
    with pytest.raises(ValueError, match="reconciled"):
        checkpoint(root, expected_run_id="44915539651", now=NOW, write=False)


def test_workflow_reconciles_after_pull_but_before_push_and_audits_afterward():
    flow = Path(".github/workflows/pipeline.yml").read_text(encoding="utf-8")
    assert flow.index("git pull --rebase") < flow.index(
        "tools.reconcile_public_health"
    ) < flow.index("git push")
    assert "git commit --amend --no-edit" in flow
    assert "tools.reconcile_public_health" in flow[
        flow.index("Audit checkpointed outputs"):]


def test_reconciler_does_not_write_telegram_or_initiate_source_fetch():
    code = Path("tools/reconcile_public_health.py").read_text(encoding="utf-8")
    for forbidden in ("send_message(", "telegram.send(", "urllib.request",
                      "requests.get(", "git push", "workflow_dispatch"):
        assert forbidden not in code



def test_full_checkpoint_rewrites_only_health_not_delivery_journals(
    tmp_path, monkeypatch,
):
    from predoc_pipeline.publish import official_calls

    root = tmp_path
    (root / "docs/data").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "docs/data/health.json").write_text(json.dumps(health()))
    source_path = root / "docs/data/official_phd_calls.json"
    source_path.write_text(json.dumps({
        "kind": "official_phd_call_observations",
        "generated_at": "2026-11-21T14:49:00Z",
        "calls": [], "sources": [],
    }))
    journal = root / "data/official_phd_calls_telegram.json"
    journal.write_text('{"version":1,"deliveries":{"old":{"state":"uncertain"}}}')
    journal_before = journal.read_bytes()
    catalogue_before = source_path.read_bytes()

    def fake_health(catalog_path, receipt_path, *, now):
        assert catalog_path == source_path
        assert receipt_path == journal
        return {
            "generated_at": "2026-11-21T14:49:00Z",
            "status": "degraded", "empty_indexes": 1,
            "document_only_indexes": 2, "eligible": 9,
        }

    monkeypatch.setattr(official_calls, "official_calls_health", fake_health)
    updated = checkpoint(
        root, expected_run_id="44915539651", now=NOW, write=True,
    )
    assert updated["status"] == "reconciled"
    assert journal.read_bytes() == journal_before
    assert source_path.read_bytes() == catalogue_before
    saved = json.loads((root / "docs/data/health.json").read_text())
    assert saved["status"] == "degraded"
    assert saved["last_run"]["run_id"] == "44915539651"
    assert saved["official_calls"]["document_only_indexes"] == 2
    assert saved["component_snapshots"]["official_calls"]["reconciled"]
    assert checkpoint(
        root, expected_run_id="44915539651", now=NOW, write=False,
    )["status"] == "checked"


def test_bad_run_id_cannot_overwrite_prior_health(tmp_path):
    (tmp_path / "docs/data").mkdir(parents=True)
    target = tmp_path / "docs/data/health.json"
    target.write_text(json.dumps(health()))
    old = target.read_bytes()
    with pytest.raises(ValueError, match="run"):
        checkpoint(tmp_path, expected_run_id="forged", now=NOW, write=True)
    assert target.read_bytes() == old
