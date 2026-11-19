"""General non-US Economics PhD *admissions* are Telegram announcements, not vacancies."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from predoc_pipeline.publish.admissions import (
    eligible_official_admissions,
    publish_official_admissions,
)

from predoc_pipeline.publish.telegram import TelegramError

NOW = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)


def _record(
    name: str = "Berlin School of Economics",
    country: str = "DE",
    url: str = "https://berlinschoolofeconomics.de/phd-program/application",
    deadline: str = "2027-01-15",
) -> dict:
    return {
        "institution": name,
        "country_code": country,
        "official_programme_url": url,
        "status": "verified",
        "checked_at": "2026-11-18T21:51:39Z",
        "deadline_iso": deadline,
        "evidence_url": url,
        "evidence_excerpt": f"Economics PhD application deadline: {deadline}.",
    }


def _catalog(*rows: dict) -> dict:
    return {
        "kind": "economics_phd_admissions_observations",
        "scope": "official_programme_sources_only",
        "source": {"deadline_values_reused": False},
        "programmes": list(rows),
    }


def test_general_phd_admissions_in_non_us_are_telegram_eligible():
    berlin = _record()
    aalto = _record(
        "Aalto University", "FI",
        "https://www.aalto.fi/en/study-options/doctoral-programme",
        "2027-01-05",
    )
    rows = eligible_official_admissions(_catalog(berlin, aalto), now=NOW)
    assert {row["institution"] for row in rows} == {
        "Berlin School of Economics", "Aalto University",
    }


def test_no_third_party_unverified_us_expired_or_unproven_location_broadcast():
    berlin = _record()
    us = _record("American University", "US", "https://www.american.edu/phd", "2027-01-15")
    unverified = {**berlin, "status": "no_explicit_deadline", "deadline_iso": None}
    expired = {**berlin, "deadline_iso": "2026-10-12"}
    stale = {**berlin, "checked_at": "2026-09-01T00:00:00Z"}
    unknown_location = _record(
        "Overseas Institution", "DE", "https://programmes.example.org/economics",
    )
    off_host = {**berlin, "evidence_url": "https://thirdparty.example.org/deadlines"}
    yearless = {**berlin, "deadline_iso": None}
    for bad in (us, unverified, expired, stale, unknown_location, off_host, yearless):
        assert eligible_official_admissions(_catalog(bad), now=NOW) == []
    assert eligible_official_admissions(
        {**_catalog(berlin), "source": {"deadline_values_reused": True}}, now=NOW
    ) == []


def test_rejects_conflicting_or_fabricated_corroboration():
    berlin = _record()
    no_year_excerpt = {**berlin, "evidence_excerpt": "Economics PhD deadline January 15"}
    missing_evidence = {**berlin, "evidence_excerpt": None}
    future_timestamp = {**berlin, "checked_at": "2027-01-01T00:00:00Z"}
    insecure_source = {**berlin, "official_programme_url": "http://university.de/phd"}
    for bad in (no_year_excerpt, missing_evidence, future_timestamp, insecure_source):
        assert eligible_official_admissions(_catalog(bad), now=NOW) == []


def test_sends_official_programme_admission_once_with_stable_receipt(tmp_path: Path):
    catalog = tmp_path / "catalog.json"
    receipts = tmp_path / "receipts.json"
    catalog.write_text(json.dumps(_catalog(_record())), encoding="utf-8")
    telegram = Mock()
    telegram.send_message.return_value = 731
    count = publish_official_admissions(
        catalog, receipts, telegram, chat_id="@existing_channel",
        enabled=True, max_messages=2, now=NOW,
    )
    assert count == 1
    assert telegram.send_message.call_count == 1
    body = telegram.send_message.call_args.kwargs["html"]
    assert "PhD programme admission" in body
    assert "not an employment vacancy" in body
    assert "Funding" in body and "not verified" in body
    assert "15 Jan 2027" in body
    assert "berlinschoolofeconomics.de" in str(telegram.send_message.call_args.kwargs)
    state = json.loads(receipts.read_text(encoding="utf-8"))
    delivery = next(iter(state["deliveries"].values()))
    assert delivery["state"] == "confirmed"
    assert delivery["message_id"] == 731
    assert delivery["deadline_iso"] == "2027-01-15"
    assert publish_official_admissions(
        catalog, receipts, telegram, chat_id="@existing_channel",
        enabled=True, max_messages=2, now=NOW + timedelta(days=1),
    ) == 0
    telegram.send_message.assert_called_once()


def test_no_duplicate_if_deadline_changes_in_same_cycle(tmp_path: Path):
    catalog = tmp_path / "catalog.json"
    receipt = tmp_path / "receipt.json"
    telegram = Mock()
    telegram.send_message.return_value = 732
    catalog.write_text(json.dumps(_catalog(_record())), encoding="utf-8")
    assert publish_official_admissions(
        catalog, receipt, telegram, chat_id="@channel", enabled=True, now=NOW,
    ) == 1
    amended = _record(deadline="2027-02-05")
    catalog.write_text(json.dumps(_catalog(amended)), encoding="utf-8")
    assert publish_official_admissions(
        catalog, receipt, telegram, chat_id="@channel",
        enabled=True, now=NOW + timedelta(days=2),
    ) == 0
    telegram.send_message.assert_called_once()


def test_uncertain_telegram_submission_is_held_and_never_blindly_retried(tmp_path: Path):
    catalog = tmp_path / "catalog.json"
    receipt = tmp_path / "receipt.json"
    catalog.write_text(json.dumps(_catalog(_record())), encoding="utf-8")
    telegram = Mock()
    telegram.send_message.side_effect = TelegramError(
        "request outcome unknown", uncertain=True,
    )
    assert publish_official_admissions(
        catalog, receipt, telegram, chat_id="@channel", enabled=True, now=NOW,
    ) == 0
    entries = json.loads(receipt.read_text())["deliveries"]
    assert next(iter(entries.values()))["state"] == "uncertain"
    telegram.send_message.side_effect = None
    assert publish_official_admissions(
        catalog, receipt, telegram, chat_id="@channel",
        enabled=True, now=NOW + timedelta(days=1),
    ) == 0
    telegram.send_message.assert_called_once()


def test_corrupt_receipts_fail_closed_and_no_send(tmp_path: Path):
    catalog = tmp_path / "catalog.json"
    receipt = tmp_path / "receipt.json"
    catalog.write_text(json.dumps(_catalog(_record())), encoding="utf-8")
    receipt.write_text("invalid json", encoding="utf-8")
    telegram = Mock()
    with pytest.raises(ValueError):
        publish_official_admissions(
            catalog, receipt, telegram, chat_id="@channel", enabled=True, now=NOW,
        )
    telegram.send_message.assert_not_called()


def test_disabled_unverified_and_no_channel_are_noop(tmp_path: Path):
    catalog = tmp_path / "catalog.json"
    receipt = tmp_path / "receipt.json"
    catalog.write_text(json.dumps(_catalog(_record())), encoding="utf-8")
    telegram = Mock()
    assert publish_official_admissions(
        catalog, receipt, telegram, chat_id="@channel", enabled=False, now=NOW,
    ) == 0
    assert publish_official_admissions(
        catalog, receipt, telegram, chat_id="", enabled=True, now=NOW,
    ) == 0
    assert publish_official_admissions(
        catalog, receipt, None, chat_id="@channel", enabled=True, now=NOW,
    ) == 0
    assert not receipt.exists()
    telegram.send_message.assert_not_called()


def test_workflow_and_pipeline_use_same_channel_without_mixing_job_ledger():
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/pipeline.yml").read_text(encoding="utf-8")
    pipeline = (root / "src/predoc_pipeline/pipeline.py").read_text(encoding="utf-8")
    assert "TELEGRAM_PHD_ADMISSIONS_ENABLED" in workflow
    assert "data/phd_admissions_telegram.json" in workflow
    assert "publish_official_admissions(" in pipeline
    assert "telegram=telegram" in pipeline
    assert "docs/data/phd_admissions.json" not in pipeline  # via settings, not vacancy feed
    assert "data/listings.ndjson" not in (root / "src/predoc_pipeline/publish/admissions.py"
                                         ).read_text(encoding="utf-8")
