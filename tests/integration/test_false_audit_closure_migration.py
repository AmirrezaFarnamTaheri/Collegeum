"""False audit closures must never erase publication receipts or source evidence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.repair_false_audit_closures import reconcile


def _prepare(root: Path):
    directory = root / "data"
    directory.mkdir(parents=True)
    rows = [
        {"id": 11, "url_hash": "a" * 64, "status": "published",
         "apply_url": "https://example.org/role/%5Bnid%5D",
         "closed_at": "2026-10-11T18:00:00Z",
         "closed_reason": "output audit: non-actionable application link (unresolved-url-template)",
         "telegram_message_id": 33, "published_at": "2026-10-09T11:00:00Z",
         "last_checked_at": None},
        {"id": 12, "url_hash": "b" * 64, "status": "published",
         "apply_url": "https://jobs.example.org/fill/real-posting",
         "closed_at": "2026-10-14T13:50:27Z",
         "closed_reason": "link no longer works (HTTP 410)",
         "telegram_message_id": 34, "published_at": "2026-10-10T11:00:00Z"},
        {"id": 13, "url_hash": "c" * 64, "status": "published",
         "apply_url": "https://jobs.example.org/fill/still-open",
         "closed_at": None, "closed_reason": None, "telegram_message_id": None},
    ]
    path = directory / "listings.ndjson"
    data = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()
    path.write_bytes(data)
    return path, data


def test_migration_is_explicit_idempotent_and_receipt_preserving(tmp_path):
    path, raw = _prepare(tmp_path)
    preview = reconcile(tmp_path)
    assert preview["candidate_ids"] == [11]
    assert not preview["applied"]
    assert path.read_bytes() == raw
    assert not (tmp_path / "build").exists()

    repaired = reconcile(tmp_path, apply=True)
    assert repaired["candidate_ids"] == [11]
    assert repaired["applied"]
    assert (tmp_path / repaired["backup"]).read_bytes() == raw

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0]["closed_at"] is None
    assert records[0]["closed_reason"] is None
    assert records[0]["telegram_message_id"] == 33
    assert records[0]["published_at"] == "2026-10-09T11:00:00Z"
    assert records[0]["apply_url"].endswith("/%5Bnid%5D")
    assert records[1]["closed_reason"] == "link no longer works (HTTP 410)"
    assert records[1]["telegram_message_id"] == 34
    assert records[2]["closed_at"] is None
    assert reconcile(tmp_path, apply=True)["candidate_ids"] == []
    assert len(list((tmp_path / "build").rglob("*.ndjson"))) == 1


def test_malformed_journal_aborts_without_creating_any_backup(tmp_path):
    path, raw = _prepare(tmp_path)
    path.write_bytes(raw + b'{"id":11,"status":"published"}\n')
    before = path.read_bytes()
    with pytest.raises(ValueError, match="duplicate journal ID"):
        reconcile(tmp_path, apply=True)
    assert path.read_bytes() == before
    assert not (tmp_path / "build").exists()


def test_audit_prefix_without_closed_at_is_not_modified(tmp_path):
    path, _raw = _prepare(tmp_path)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    records[0]["closed_at"] = None
    path.write_text("".join(json.dumps(row) + "\n" for row in records))
    before = path.read_bytes()
    assert reconcile(tmp_path, apply=True)["candidate_ids"] == []
    assert path.read_bytes() == before

def test_unicode_line_separator_remains_inside_ndjson_record(tmp_path):
    path = tmp_path / "data" / "listings.ndjson"
    path.parent.mkdir(parents=True)
    record = {"id": 31, "status": "published", "title": "Economics\u2028Research",
              "closed_at": "2026-10-11T18:00:00Z",
              "closed_reason": "output audit: non-actionable application link (template)"}
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    assert reconcile(tmp_path)["candidate_ids"] == [31]
