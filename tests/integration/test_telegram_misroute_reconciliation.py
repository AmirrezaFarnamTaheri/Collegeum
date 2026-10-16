"""Historical Telegram corrections are explicit, reviewable, and never broadcast new posts."""
from __future__ import annotations

import pytest

from tools.reconcile_telegram_misroutes import (
    apply_corrections, correction_html, plan_records,
)


def row(id, message_id, *, title="Research Fellow", degree="phd", status="published",
        url="https://example.org/jobs/one"):
    return {
        "id": id, "telegram_message_id": message_id, "status": status,
        "title": title, "summary": "Econometrics and applied economics.",
        "min_degree": degree, "degree_note": None, "apply_url": url,
        "institution": "University of Warwick", "country": "United Kingdom",
        "city": "Coventry",
    }


class FakeTelegram:
    def __init__(self):
        self.calls = []

    def call(self, method, payload):
        self.calls.append((method, payload))
        return True


def test_only_nonpredocs_with_confirmed_public_receipts_are_correction_candidates():
    records = [
        row(1, 23), row(2, 24, title="Postdoctoral Fellow", degree="unstated"),
        row(3, 25, title="Predoctoral Research Assistant", degree="bachelors"),
        row(4, None), row(5, 26, status="pending"),
    ]
    plan = plan_records(records)
    assert [item.listing_id for item in plan] == [1, 2]
    assert [item.kind for item in plan] == ["research", "postdoc"]


def test_shared_digest_message_is_not_safe_to_edit():
    records = [
        row(1, 90),
        row(2, 90, title="Predoctoral Research Assistant", degree="bachelors"),
        row(3, 91),
    ]
    plan = plan_records(records)
    assert [(item.listing_id, item.shared_receipt) for item in plan] == [(1, True), (3, False)]
    sender = FakeTelegram()
    with pytest.raises(ValueError, match="shared"):
        apply_corrections(
            plan, reviewed_ids={1, 3}, journal_sha256="a" * 64,
            confirm_sha256="a" * 64, channel="-100123",
            confirm_channel="-100123", client=sender,
        )
    assert sender.calls == []


def test_explicit_exact_review_required_before_any_telegram_edit():
    candidates = plan_records([row(7, 35)])
    sender = FakeTelegram()
    common = dict(journal_sha256="b" * 64, confirm_sha256="b" * 64,
                  channel="@collegeum", confirm_channel="@collegeum", client=sender)
    with pytest.raises(ValueError, match="review"):
        apply_corrections(candidates, reviewed_ids=set(), **common)
    with pytest.raises(ValueError, match="digest"):
        apply_corrections(candidates, reviewed_ids={7}, **{**common, "confirm_sha256": "c" * 64})
    with pytest.raises(ValueError, match="channel"):
        apply_corrections(candidates, reviewed_ids={7}, **{**common, "confirm_channel": "@another"})
    with pytest.raises(ValueError, match="candidate"):
        apply_corrections(candidates, reviewed_ids={8}, **common)
    assert sender.calls == []


def test_only_approved_message_is_corrected_in_place_no_new_telegram_posts():
    candidates = plan_records([row(7, 35), row(8, 36, title="Postdoctoral Fellow")])
    sender = FakeTelegram()
    report = apply_corrections(
        candidates, reviewed_ids={7}, journal_sha256="d" * 64,
        confirm_sha256="d" * 64, channel="-100123",
        confirm_channel="-100123", client=sender,
    )
    assert report == {"edited_listing_ids": [7], "failed": []}
    assert len(sender.calls) == 1
    method, payload = sender.calls[0]
    assert method == "editMessageText"
    assert payload["chat_id"] == "-100123"
    assert payload["message_id"] == 35
    assert "Correction" in payload["text"]
    assert "not a predoc" in payload["text"]
    assert "sendMessage" not in [method for method, _ in sender.calls]


def test_corrective_copy_escapes_advert_and_does_not_relink_broken_template():
    candidates = plan_records([
        row(11, 19, title="Research <Fellow> & Economist",
            url="https://example.org/job/%5Bnid%5D"),
    ])
    html = correction_html(candidates[0])
    assert "Research &lt;Fellow&gt; &amp; Economist" in html
    assert "href=" not in html
    assert "%5Bnid%5D" not in html


def test_historical_journal_is_never_modified_by_planning(tmp_path):
    import hashlib
    import json
    from tools.reconcile_telegram_misroutes import plan_file

    file = tmp_path / "listings.ndjson"
    original = json.dumps(row(2, 101), ensure_ascii=False).encode() + b"\n"
    file.write_bytes(original)
    digest, plan = plan_file(file)
    assert digest == hashlib.sha256(original).hexdigest()
    assert [p.listing_id for p in plan] == [2]
    assert file.read_bytes() == original
