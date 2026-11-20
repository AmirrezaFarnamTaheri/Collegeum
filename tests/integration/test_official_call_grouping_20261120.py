"""Regression contracts for consolidated official PhD calls and Home-fee bursaries."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import Mock

from predoc_pipeline.publish.official_calls import (
    call_key,
    eligible_calls,
    official_calls_health,
    publish_official_calls,
)
from tools.update_official_calls import extract_call

NOW = datetime(2026, 11, 20, 10, tzinfo=UTC)
HENLEY_ROOT = "https://www.henley.ac.uk/study/phds/"
GROUP = "henley-departmental-2027"
READING = (
    "https://www.reading.ac.uk/doctoral-researcher-college/funding/"
    "phd-studentships/uor-phd-bursaries"
)


def _henley(suffix: str, title: str, *, posting_group: str | None = GROUP):
    url = HENLEY_ROOT + suffix
    row = {
        "source_id": "henley-" + suffix, "institution": "Henley Business School",
        "country_code": "UK", "kind": "phd_studentship",
        "title": title, "status": "verified", "intake_year": 2027,
        "official_url": url, "evidence_url": url,
        "evidence_excerpt": "Studentship applications close on 21 February 2027",
        "deadline_iso": "2027-02-21", "deadline_kind": "funding",
        "recommended_admission_iso": "2027-01-10",
        "location_evidence_url": url,
        "location_evidence": "UK: official national institutional domain henley.ac.uk",
        "checked_at": NOW.isoformat(), "subject_scope": "multidisciplinary",
    }
    if posting_group is not None:
        row["posting_group"] = posting_group
    return row


def _catalog(*rows):
    return {
        "kind": "official_phd_call_observations", "version": 1,
        "sources": [{"status": "ok"}], "calls": list(rows),
    }


def _publish(tmp_path, rows, *, telegram=None, reserve_intent=None):
    source = tmp_path / "calls.json"
    ledger = tmp_path / "receipts.json"
    source.write_text(json.dumps(_catalog(*rows)), encoding="utf-8")
    telegram = telegram or Mock()
    telegram.send_message.return_value = 601
    result = publish_official_calls(
        source, ledger, telegram, chat_id="@channel", enabled=True,
        max_messages=2, now=NOW, reserve_intent=reserve_intent,
    )
    return result, telegram, ledger, source


def test_five_related_henley_positions_make_one_message_with_five_official_links(tmp_path):
    rows = [
        _henley("accounting", "Accounting PhD Opportunities"),
        _henley("entrepreneurship", "Entrepreneurship and Innovation PhD Opportunities"),
        _henley("informatics", "Informatics and Operations PhD Opportunities"),
        _henley("strategy", "International Business and Strategy PhD Opportunities"),
        _henley("leadership", "PhD in Leadership, Organisations and Behaviour"),
    ]
    count, telegram, ledger, source = _publish(tmp_path, rows)
    assert count == 1
    assert telegram.send_message.call_count == 1
    kwargs = telegram.send_message.call_args.kwargs
    html = kwargs["html"]
    assert "5" in html and "Henley Business School" in html
    assert "21 Feb 2027" in html and "10 Jan 2027" in html
    for row in rows:
        assert row["title"] in html
    buttons = kwargs["keyboard"]["inline_keyboard"]
    assert len(buttons) == 5
    assert {button[0]["url"] for button in buttons} == {
        row["official_url"] for row in rows
    }
    receipts = json.loads(ledger.read_text(encoding="utf-8"))["deliveries"]
    assert set(receipts) == {call_key(row) for row in rows}
    assert {value["message_id"] for value in receipts.values()} == {601}
    assert {value["state"] for value in receipts.values()} == {"confirmed"}
    assert publish_official_calls(
        source, ledger, telegram, chat_id="@channel", enabled=True, now=NOW,
    ) == 0
    assert telegram.send_message.call_count == 1
    health = official_calls_health(source, ledger, now=NOW)
    assert health["confirmed"] == 5
    assert health["confirmed_messages"] == 1


def test_legacy_henley_2026_identity_is_not_misrepresented_as_2026_intake(tmp_path):
    # The 2027/28 funding pages historically hashed as intake_year=2026 due
    # to an earlier 2026/27 *closed* date. Avoid publishing that bad label
    # or automatically changing keys and triggering duplicates.
    rows = [
        _henley("accounting", "Accounting PhD Opportunities"),
        _henley("strategy", "International Business and Strategy PhD Opportunities"),
    ]
    for row in rows:
        row["intake_year"] = 2026
    count, telegram, _, _ = _publish(tmp_path, rows)
    assert count == 1
    assert "Intake: 2026" not in telegram.send_message.call_args.kwargs["html"]


def test_group_is_never_inferred_from_same_university_or_deadline_alone(tmp_path):
    rows = [
        _henley("one", "Accounting PhD Opportunities", posting_group=None),
        _henley("two", "Strategy PhD Opportunities", posting_group=None),
    ]
    count, telegram, _, _ = _publish(tmp_path, rows)
    assert count == 2
    assert telegram.send_message.call_count == 2


def test_different_application_timing_does_not_silently_merge_positions(tmp_path):
    first = _henley("one", "Accounting PhD Opportunities")
    second = _henley("two", "Strategy PhD Opportunities")
    second["recommended_admission_iso"] = "2027-01-12"
    count, telegram, _, _ = _publish(tmp_path, [first, second])
    assert count == 2
    assert telegram.send_message.call_count == 2


def test_group_intents_are_all_reserved_before_the_one_telegram_send(tmp_path):
    rows = [_henley(str(i), f"Department {i} PhD Opportunities") for i in range(3)]
    reserved = []
    telegram = Mock()

    def send(**kwargs):
        assert len(reserved) == 3
        assert {key for namespace, key, operation in reserved} == {
            call_key(row) for row in rows
        }
        assert all(namespace == "calls" and operation == "initial"
                   for namespace, _, operation in reserved)
        return 601

    telegram.send_message.side_effect = send
    count, _, ledger, _ = _publish(
        tmp_path, rows, telegram=telegram,
        reserve_intent=lambda namespace, key, operation:
            reserved.append((namespace, key, operation)),
    )
    assert count == 1
    assert telegram.send_message.call_count == 1
    assert len(json.loads(ledger.read_text())["deliveries"]) == 3


def test_one_uncertain_group_send_holds_every_member_and_never_retries(tmp_path):
    from predoc_pipeline.publish.telegram import TelegramError

    rows = [_henley("one", "Accounting PhD Opportunities"),
            _henley("two", "Strategy PhD Opportunities")]
    telegram = Mock()
    telegram.send_message.side_effect = TelegramError("timeout", uncertain=True)
    count, _, ledger, source = _publish(tmp_path, rows, telegram=telegram)
    assert count == 0
    assert telegram.send_message.call_count == 1
    receipts = json.loads(ledger.read_text())["deliveries"]
    assert {item["state"] for item in receipts.values()} == {"uncertain"}
    telegram.send_message.side_effect = None
    assert publish_official_calls(
        source, ledger, telegram, chat_id="@channel", enabled=True, now=NOW,
    ) == 0
    assert telegram.send_message.call_count == 1


def test_approved_source_group_is_carried_into_verified_observations():
    source = {
        "id": "henley-accounting", "institution": "Henley Business School",
        "country_code": "UK", "mode": "detail",
        "url": HENLEY_ROOT + "accounting", "posting_group": GROUP,
        "title": "Accounting PhD Studentships",
    }
    html = """<h1>Accounting PhD Opportunities</h1>
    <p>We offer postgraduate studentships in business and finance.
    Studentship applications for the 2027/28 academic year are now open
    and will close on 21 February 2027. We strongly advise submitting your
    application no later than 10 January 2027.</p>"""
    row = extract_call(html, url=source["url"], source=source, now=NOW)
    assert row["status"] == "verified"
    assert row["posting_group"] == GROUP


def test_reading_home_phd_bursary_is_discovered_as_fee_only_funding():
    source = {
        "id": "reading-home-phd-bursaries", "institution": "University of Reading",
        "country_code": "UK", "mode": "detail", "url": READING,
        "subject_scope": "multidisciplinary",
    }
    html = """<h1>University of Reading PhD Home fee Bursaries</h1>
    <p>PhD bursaries are available for new applicants intending to commence
    full-time PhD study in September 2027. The bursaries include PhD tuition
    fees at the Home rate for up to four years, but no subsistence stipend.</p>
    <h2>Deadline for applications</h2>
    <p>The deadline by which to apply is 30th April 2027.</p>"""
    row = extract_call(html, url=READING, source=source, now=NOW)
    assert row["status"] == "verified"
    assert row["kind"] == "phd_bursary"
    assert row["deadline_iso"] == "2027-04-30"
    assert row["deadline_kind"] == "funding"
    assert row["intake_year"] == 2027
    assert eligible_calls(_catalog(row), now=NOW) == [row]


def test_home_bursary_source_is_registered_for_robots_checked_refresh():
    from pathlib import Path
    sources = json.loads(
        Path("config/official_phd_calls_sources.json").read_text(encoding="utf-8")
    )["sources"]
    assert any(
        row["id"] == "reading-home-phd-bursaries" and row["url"] == READING
        and row["mode"] == "detail"
        for row in sources
    )
