"""Audit both durable official-delivery journals alongside source snapshots."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from tools.reconcile_public_health import checkpoint

NOW = datetime(2026, 11, 21, 15, tzinfo=UTC)
RUN_ID = "44915539651"
SOURCES = {
    "docs/data/official_phd_calls.json":
        {"generated_at": "2026-11-21T14:49:00Z", "sources": [], "calls": []},
    "docs/data/phd_admissions.json":
        {"generated_at": "2026-11-21T14:47:00Z", "programmes": []},
    "data/life_sources_health.json":
        {"checked_at": "2026-11-21T14:50:00Z", "sources": []},
    "data/career_health.json":
        {"checked_at": "2026-11-21T14:52:00Z", "sources": []},
    "docs/data/listings.json":
        {"generated_at": "2026-11-21T14:55:00Z", "listings": []},
}
JOURNALS = (
    ("official_calls", "data/official_phd_calls_telegram.json"),
    ("phd_admissions", "data/phd_admissions_telegram.json"),
)


@pytest.fixture
def checkpoint_files(tmp_path, monkeypatch):
    from predoc_pipeline.publish import official_calls

    root = tmp_path
    for path, payload in SOURCES.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload))
    for name, path in JOURNALS:
        target = root / path
        target.write_text(json.dumps({
            "version": 1, "deliveries": {
                name: {"state": "confirmed", "message_id": 91},
            },
        }))
    health = root / "docs/data/health.json"
    health.write_text(json.dumps({
        "generated_at": "2026-11-21T14:55:00Z",
        "status": "degraded",
        "last_run": {
            "run_id": RUN_ID, "outcome": "partial",
            "sources": {
                "total": 1, "successful": 0, "empty": 0,
                "failed": 1, "partial": 0, "skipped": 0,
            },
        },
        "official_calls": {"generated_at": "2026-11-21T13:00:00Z"},
    }))
    monkeypatch.setattr(
        official_calls, "official_calls_health",
        lambda catalog_path, receipt_path, *, now: {
            "generated_at": "2026-11-21T14:49:00Z",
            "status": "degraded", "eligible": 0, "unpublished": 0,
        },
    )
    return root


def test_same_source_timestamp_cannot_hide_a_mutated_delivery_journal(
    checkpoint_files,
):
    root = checkpoint_files
    saved = {
        name: (root / path).read_bytes()
        for name, path in JOURNALS
    }
    assert checkpoint(root, expected_run_id=RUN_ID, now=NOW, write=True)[
        "status"
    ] == "reconciled"
    health = root / "docs/data/health.json"
    before = health.read_bytes()
    published = json.loads(before)
    assert set(published["delivery_journal_sha256"]) == {
        "official_calls", "phd_admissions",
    }
    assert all(len(x) == 64 for x in published["delivery_journal_sha256"].values())
    assert checkpoint(root, expected_run_id=RUN_ID, now=NOW, write=False)[
        "status"
    ] == "checked"

    for name, path in JOURNALS:
        target = root / path
        target.write_text(json.dumps({
            "version": 1, "deliveries": {
                name: {"state": "uncertain", "message_id": 91},
            },
        }))
        with pytest.raises(ValueError, match="delivery journal fingerprint"):
            checkpoint(root, expected_run_id=RUN_ID, now=NOW, write=False)
        assert health.read_bytes() == before
        target.write_bytes(saved[name])
    assert checkpoint(root, expected_run_id=RUN_ID, now=NOW, write=False)[
        "status"
    ] == "checked"


def test_missing_or_replaced_delivery_history_is_not_silent(checkpoint_files):
    root = checkpoint_files
    checkpoint(root, expected_run_id=RUN_ID, now=NOW, write=True)
    _, path = JOURNALS[0]
    journal = root / path
    original = journal.read_bytes()
    journal.unlink()
    with pytest.raises(ValueError, match="delivery journal fingerprint"):
        checkpoint(root, expected_run_id=RUN_ID, now=NOW, write=False)
    journal.write_bytes(original)
    assert checkpoint(root, expected_run_id=RUN_ID, now=NOW, write=False)[
        "status"
    ] == "checked"


def test_corrupt_journal_halts_health_reconciliation_without_overwriting_it(
    checkpoint_files,
):
    root = checkpoint_files
    journal = root / JOURNALS[1][1]
    journal.write_text("<html>Login challenge</html>")
    path = root / "docs/data/health.json"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="delivery journal"):
        checkpoint(root, expected_run_id=RUN_ID, now=NOW, write=True)
    assert path.read_bytes() == before


def test_delivery_journal_hashes_are_observations_not_mutations(checkpoint_files):
    root = checkpoint_files
    prior = {name: (root / path).read_bytes() for name, path in JOURNALS}
    checkpoint(root, expected_run_id=RUN_ID, now=NOW, write=True)
    assert all((root / path).read_bytes() == prior[name] for name, path in JOURNALS)



@pytest.mark.parametrize("file_path", [
    "data/official_phd_calls_telegram.json",
    "data/phd_admissions_telegram.json",
    "docs/data/official_phd_calls.json",
    "docs/data/phd_admissions.json",
])
def test_dangling_symlink_cannot_masquerade_as_missing_health_input(
    checkpoint_files, file_path,
):
    root = checkpoint_files
    target = root / file_path
    target.unlink()
    target.symlink_to(root / "absent-institutional-file.json")
    health = root / "docs/data/health.json"
    before = health.read_bytes()
    with pytest.raises(ValueError, match="Untrusted|symlink"):
        checkpoint(root, expected_run_id=RUN_ID, now=NOW, write=True)
    assert health.read_bytes() == before
