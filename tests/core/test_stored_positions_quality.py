"""Stored-position audit is read-only and preserves both storage grains."""
import json
from datetime import UTC, datetime
from pathlib import Path

from tools.audit_stored_positions import audit


def test_whole_stored_inventory_has_no_identity_or_receipt_corruption():
    root = Path(__file__).resolve().parents[2]
    result = audit(root, now=datetime(2026, 11, 15, 8, tzinfo=UTC))
    assert result["journal"]["rows"] >= 437
    assert result["career"]["rows"] >= 98
    assert result["critical_invariants"] == []
    assert result["journal"]["country_disagreement_ids"] == []
    assert result["career"]["numeric_location_keys"] == []
    assert result["journal"]["confirmed_phd_receipts"] >= 16
    # Predoc legacy deliveries intentionally use a separate pre-PhD receipt
    # scheme and must never be counted as failed new PhD posts.
    assert result["journal"]["legacy_predoc_message_ids"] >= 1


def test_audit_surfaces_duplicate_keys_and_true_missing_confirmed_receipts(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/listings.ndjson").write_text(
        "\n".join(json.dumps(item) for item in [
            {"id": 1, "url_hash": "a" * 64, "country": "United States",
             "telegram_delivery_state": "confirmed", "telegram_message_id": None},
            {"id": 1, "url_hash": "a" * 64, "country": "United States",
             "telegram_delivery_state": "not_attempted", "telegram_message_id": 20},
        ]) + "\n", encoding="utf-8",
    )
    (tmp_path / "data/career_jobs.ndjson").write_text(
        "\n".join(json.dumps(item) for item in [
            {"key": "career:1", "location": "7"},
            {"key": "career:1", "location": "Germany"},
        ]) + "\n", encoding="utf-8",
    )
    result = audit(tmp_path)
    assert len(result["critical_invariants"]) == 4
    assert result["career"]["numeric_location_keys"] == ["career:1"]
    assert result["journal"]["legacy_predoc_message_ids"] == 1
