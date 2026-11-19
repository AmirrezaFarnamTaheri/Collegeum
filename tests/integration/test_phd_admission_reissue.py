"""The two earlier admissions messages require explicit, auditable replacement."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from predoc_pipeline.publish.admissions import (
    _delivery_key,
    authorize_reissue,
    publish_official_admissions,
)


def test_confirmed_message_is_unchanged_until_deletion_is_explicit(tmp_path):
    now = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    evidence = "https://berlinschoolofeconomics.de/phd-program/application"
    berlin = {
        "institution": "Berlin School of Economics", "country_code": "DE",
        "status": "verified", "deadline_iso": "2027-01-15",
        "checked_at": "2026-11-19T10:00:00Z",
        "official_programme_url": evidence, "evidence_url": evidence,
        "evidence_excerpt": "Economics PhD deadline January 15, 2027",
    }
    catalog = tmp_path / "catalog.json"
    receipts = tmp_path / "receipts.json"
    catalog.write_text(json.dumps({
        "kind": "economics_phd_admissions_observations",
        "scope": "official_programme_sources_only",
        "source": {"deadline_values_reused": False},
        "programmes": [berlin],
    }))
    key = _delivery_key(berlin)
    original = {
        "version": 1,
        "deliveries": {
            key: {
                "state": "confirmed", "message_id": 129,
                "institution": "Berlin School of Economics",
                "country_code": "DE", "deadline_iso": "2027-01-15",
                "sent_at": "2026-11-19T09:01:41Z",
                "evidence_url": evidence,
            },
        },
    }
    receipts.write_text(json.dumps(original), encoding="utf-8")
    bot = Mock()
    bot.send_message.return_value = 200

    with pytest.raises(ValueError):
        authorize_reissue(
            receipts, institution="Berlin School of Economics", country_code="DE",
            original_message_id=129, deleted_confirmed=False, now=now,
        )
    with pytest.raises(ValueError):
        authorize_reissue(
            receipts, institution="Berlin School of Economics", country_code="DE",
            original_message_id=128, deleted_confirmed=True, now=now,
        )
    assert json.loads(receipts.read_text()) == original
    assert publish_official_admissions(
        catalog, receipts, bot, chat_id="@channel", enabled=True, now=now,
    ) == 0
    bot.send_message.assert_not_called()

    authorize_reissue(
        receipts, institution="Berlin School of Economics", country_code="DE",
        original_message_id=129, deleted_confirmed=True, now=now,
    )
    pending = json.loads(receipts.read_text())["deliveries"][key]
    assert pending["state"] == "reissue_authorized"
    assert pending["prior_message_id"] == 129
    with pytest.raises(ValueError):
        authorize_reissue(
            receipts, institution="Berlin School of Economics", country_code="DE",
            original_message_id=129, deleted_confirmed=True, now=now,
        )
    assert publish_official_admissions(
        catalog, receipts, bot, chat_id="@channel", enabled=True, now=now,
    ) == 1
    restored = json.loads(receipts.read_text())["deliveries"][key]
    assert restored["state"] == "confirmed"
    assert restored["message_id"] == 200
    assert restored["replaces_message_id"] == 129
    assert restored["history"][0]["message_id"] == 129
    assert publish_official_admissions(
        catalog, receipts, bot, chat_id="@channel", enabled=True, now=now,
    ) == 0
    bot.send_message.assert_called_once()
