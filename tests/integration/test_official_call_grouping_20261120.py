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
from tools.ingestion_watchdog import evaluate_official_calls_trigger
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


def _open_henley_2027():
    url = HENLEY_ROOT + "accounting-and-financial-management"
    source = {
        "id": "henley-finance-accounting",
        "institution": "Henley Business School",
        "country_code": "UK", "mode": "detail", "url": url,
        "title": "Finance and Accounting PhD Studentships",
        "posting_group": GROUP,
    }
    html = """<h1>Accounting PhD Opportunities</h1>
    <p>Our PhD in Accounting is a Finance and Accounting research programme.</p>
    <p>Studentship applications for the 2026/27 academic year are now closed.</p>
    <p>Studentship applications for the 2027/28 academic year are now open
    and will close on 21 February 2027.
    We strongly advise submitting your application no later than
    10 January 2027.</p>"""
    return extract_call(html, url=url, source=source, now=NOW)


def test_henley_intake_comes_from_open_cycle_not_previous_closed_cycle():
    row = _open_henley_2027()
    assert row["status"] == "verified"
    assert row["intake_year"] == 2027
    assert row["deadline_iso"] == "2027-02-21"


def test_corrected_intake_does_not_republish_legacy_confirmed_telegram_call(tmp_path):
    row = _open_henley_2027()
    assert row["intake_year"] == 2027
    legacy = {**row, "intake_year": 2026}
    assert call_key(row) != call_key(legacy)
    source = tmp_path / "calls.json"
    ledger = tmp_path / "receipts.json"
    source.write_text(json.dumps(_catalog(row)), encoding="utf-8")
    receipt = {
        "state": "confirmed", "message_id": 136,
        "official_url": row["official_url"],
        "institution": row["institution"],
        "deadline_iso": row["deadline_iso"],
        "intake_year": 2026,
        "sent_at": "2026-11-19T23:55:55Z",
    }
    ledger.write_text(json.dumps({
        "version": 1, "deliveries": {call_key(legacy): receipt},
    }), encoding="utf-8")
    telegram = Mock()
    assert publish_official_calls(
        source, ledger, telegram, chat_id="@channel", enabled=True, now=NOW,
    ) == 0
    telegram.send_message.assert_not_called()
    assert official_calls_health(source, ledger, now=NOW)["unpublished"] == 0

    runs = [{
        "name": "predoc-pipeline", "head_branch": "main",
        "status": "completed", "created_at": "2026-11-20T06:00:00Z",
    }]
    assert not evaluate_official_calls_trigger(
        _catalog(row), {"version": 1, "deliveries": {call_key(legacy): receipt}},
        runs, now=NOW,
    ).dispatch


def test_new_future_cycle_still_publishes_on_same_university_url(tmp_path):
    future = _henley("accounting-and-financial-management", "Accounting PhD Opportunities")
    prior = {**future, "deadline_iso": "2026-12-21", "intake_year": 2026}
    # New future funding round on the same official departmental URL.
    future["intake_year"] = 2027
    future["posting_group"] = None
    old_receipt = {
        "state": "confirmed", "message_id": 136,
        "official_url": prior["official_url"],
        "institution": prior["institution"],
        "deadline_iso": prior["deadline_iso"],
        "intake_year": prior["intake_year"],
        "sent_at": "2026-11-19T23:55:55Z",
    }
    catalog = tmp_path / "catalog.json"
    ledger = tmp_path / "ledger.json"
    catalog.write_text(json.dumps(_catalog(future)), encoding="utf-8")
    ledger.write_text(json.dumps({
        "version": 1, "deliveries": {call_key(prior): old_receipt},
    }), encoding="utf-8")
    telegram = Mock()
    telegram.send_message.return_value = 777
    assert publish_official_calls(
        catalog, ledger, telegram, chat_id="@channel", enabled=True, now=NOW,
    ) == 1
    assert telegram.send_message.call_count == 1


def test_partial_declared_group_is_held_not_emitted_as_single_posts(tmp_path):
    rows = [
        _henley("accounting", "Accounting PhD Opportunities"),
        _henley("strategy", "Strategy PhD Opportunities"),
    ]
    for row in rows:
        row["posting_group_expected"] = 5
    count, telegram, ledger, source = _publish(tmp_path, rows)
    assert count == 0
    telegram.send_message.assert_not_called()
    assert not ledger.exists()
    health = official_calls_health(source, ledger, now=NOW)
    assert health["unpublished"] == 2
    assert health["group_waiting"] == 2


def test_completed_declared_group_emits_exactly_one_digest(tmp_path):
    rows = [
        _henley(str(i), f"Department {i} PhD Opportunities")
        for i in range(5)
    ]
    for row in rows:
        row["posting_group_expected"] = 5
    count, telegram, ledger, _ = _publish(tmp_path, rows)
    assert count == 1
    assert telegram.send_message.call_count == 1
    assert len(json.loads(ledger.read_text())["deliveries"]) == 5


def test_validated_henley_registry_explicitly_declares_group_membership():
    from pathlib import Path
    config = json.loads(Path("config/official_phd_calls_sources.json").read_text())
    henley = [item for item in config["sources"] if item["id"].startswith("henley-")]
    assert len(henley) == 5
    assert {row["posting_group_expected"] for row in henley} == {5}


def test_watchdog_does_not_dispatch_for_incomplete_reviewed_group():
    rows = [_henley(str(i), f"Department {i} PhD Opportunities")
            for i in range(2)]
    for row in rows:
        row["posting_group_expected"] = 5
    runs = [{
        "name": "predoc-pipeline", "head_branch": "main",
        "status": "completed", "created_at": "2026-11-20T06:00:00Z",
    }]
    decision = evaluate_official_calls_trigger(
        _catalog(*rows), {"version": 1, "deliveries": {}}, runs, now=NOW,
    )
    assert not decision.dispatch
    assert decision.reason == "no-new-eligible-official-calls"


def test_watchdog_dispatches_completed_reviewed_group():
    rows = [_henley(str(i), f"Department {i} PhD Opportunities")
            for i in range(5)]
    for row in rows:
        row["posting_group_expected"] = 5
    runs = [{
        "name": "predoc-pipeline", "head_branch": "main",
        "status": "completed", "created_at": "2026-11-20T06:00:00Z",
    }]
    decision = evaluate_official_calls_trigger(
        _catalog(*rows), {"version": 1, "deliveries": {}}, runs, now=NOW,
    )
    assert decision.dispatch


def test_group_with_existing_member_receipt_does_not_publish_late_duplicates(tmp_path):
    rows = [_henley(str(i), f"Department {i} PhD Opportunities")
            for i in range(5)]
    for row in rows:
        row["posting_group_expected"] = 5
    old = rows[0]
    ledger = tmp_path / "ledger.json"
    catalog = tmp_path / "catalog.json"
    ledger.write_text(json.dumps({
        "version": 1,
        "deliveries": {call_key(old): {
            "state": "confirmed", "message_id": 514,
            "official_url": old["official_url"],
            "institution": old["institution"],
            "deadline_iso": old["deadline_iso"],
            "sent_at": "2026-11-19T23:55:55Z",
        }},
    }), encoding="utf-8")
    catalog.write_text(json.dumps(_catalog(*rows)), encoding="utf-8")
    telegram = Mock()
    assert publish_official_calls(
        catalog, ledger, telegram, chat_id="@channel", enabled=True, now=NOW,
    ) == 0
    telegram.send_message.assert_not_called()
    health = official_calls_health(catalog, ledger, now=NOW)
    assert health["unpublished"] == 4
    assert health["group_waiting"] == 4


def test_all_conflicting_duplicate_records_remain_suppressed():
    rows = [
        _henley("accounting", "Accounting PhD Opportunities", posting_group=None),
        _henley("accounting", "Accounting PhD Opportunities", posting_group=None),
        _henley("accounting", "Accounting PhD Opportunities", posting_group=None),
    ]
    rows[1]["deadline_iso"] = "2027-03-01"
    assert eligible_calls(_catalog(*rows), now=NOW) == []


def test_bool_intake_and_invalid_recommended_dates_fail_closed():
    row = _henley("accounting", "Accounting PhD Opportunities")
    assert eligible_calls(_catalog({**row, "intake_year": True}), now=NOW) == []
    assert eligible_calls(_catalog({
        **row, "recommended_admission_iso": "2027-02-32",
    }), now=NOW) == []
    assert eligible_calls(_catalog({
        **row, "recommended_admission_iso": "2027-03-10",
    }), now=NOW) == []


def test_legacy_alias_requires_same_official_funding_deadline_and_institution():
    from predoc_pipeline.core.official_call_rules import receipt_key

    current = _henley("accounting", "Accounting PhD Opportunities")
    current["intake_year"] = 2027
    old = {**current, "intake_year": 2026}
    receipt = {
        "state": "confirmed", "message_id": 136,
        "institution": current["institution"],
        "official_url": current["official_url"],
        "deadline_iso": current["deadline_iso"],
        "intake_year": 2026,
        "title": current["title"],
    }
    assert receipt_key(current, {call_key(old): receipt}) == call_key(old)
    for modification in (
        {"institution": "Unrelated University"},
        {"deadline_iso": "2027-03-01"},
        {"official_url": HENLEY_ROOT + "different-call"},
        {"intake_year": 2024},
    ):
        changed = {**receipt, **modification}
        assert receipt_key(current, {call_key(old): changed}) is None
    # An editorial title change on the same official URL/deadline is not a new call.
    renamed = {**receipt, "title": "Renamed Accounting Studentship"}
    assert receipt_key(current, {call_key(old): renamed}) == call_key(old)


def test_mixed_deadline_group_is_held_when_member_count_is_declared(tmp_path):
    rows = [
        _henley(str(i), f"Department {i} PhD Opportunities") for i in range(5)
    ]
    for row in rows:
        row["posting_group_expected"] = 5
    rows[-1]["deadline_iso"] = "2027-02-22"
    count, telegram, _, _ = _publish(tmp_path, rows)
    assert count == 0
    telegram.send_message.assert_not_called()


def test_unexpected_group_more_than_six_never_truncates_and_sends(tmp_path):
    rows = [
        _henley(str(i), f"Department {i} PhD Opportunities") for i in range(7)
    ]
    count, telegram, ledger, _ = _publish(tmp_path, rows)
    assert count == 0
    telegram.send_message.assert_not_called()
    assert not ledger.exists()


def test_partial_group_reservation_failure_holds_every_member(tmp_path):
    rows = [
        _henley(str(i), f"Department {i} PhD Opportunities") for i in range(3)
    ]
    telegram = Mock()
    reservations = []

    def reserve(namespace, key, operation):
        reservations.append(key)
        if len(reservations) == 2:
            raise OSError("simulated Github reservation outage")

    import pytest

    with pytest.raises(OSError):
        _publish(tmp_path, rows, telegram=telegram, reserve_intent=reserve)
    telegram.send_message.assert_not_called()
    ledger = json.loads((tmp_path / "receipts.json").read_text())
    assert len(ledger["deliveries"]) == 3
    assert {entry["state"] for entry in ledger["deliveries"].values()} == {"pending"}


def test_bursary_is_eligible_for_watchdog_when_verified():
    from tools.update_official_calls import extract_call

    source = {
        "id": "reading-home-phd-bursaries", "institution": "University of Reading",
        "country_code": "UK", "mode": "detail", "url": READING,
        "subject_scope": "multidisciplinary",
    }
    html = """<h1>University of Reading PhD Home fee Bursaries</h1>
    <p>PhD bursaries for applicants intending to commence
    full-time PhD study in September 2027.</p>
    <h2>Deadline for applications</h2>
    <p>The deadline by which to apply is 30th April 2027.</p>"""
    row = extract_call(html, url=READING, source=source, now=NOW)
    assert row["status"] == "verified"
    runs = [{
        "name": "predoc-pipeline", "head_branch": "main",
        "status": "completed", "created_at": "2026-11-20T06:00:00Z",
    }]
    decision = evaluate_official_calls_trigger(
        _catalog(row), {"version": 1, "deliveries": {}}, runs, now=NOW,
    )
    assert decision.dispatch


def test_non_grouped_different_funding_calls_stay_separate(tmp_path):
    iebs = [
        _henley("economics", "Economics PhD Scholarship", posting_group=None),
        _henley("climate", "Climate Economics PhD Fellowship", posting_group=None),
    ]
    iebs[0]["kind"] = "phd_scholarship"
    iebs[0]["deadline_kind"] = "scholarship"
    iebs[1]["kind"] = "phd_fellowship"
    iebs[1]["deadline_kind"] = "scholarship"
    count, telegram, _, _ = _publish(tmp_path, iebs)
    assert count == 2
    assert telegram.send_message.call_count == 2


def test_reviewed_group_requires_matching_count_and_same_institution():
    from tools.update_official_calls import validate_sources

    def source(i, *, group="sample-research-bundle", count=3, institution="School A"):
        return {
            "id": f"source-{i}", "institution": institution,
            "country_code": "UK", "mode": "detail",
            "url": f"https://school.ac.uk/phds/{i}",
            "posting_group": group, "posting_group_expected": count,
        }
    config = {
        "kind": "official_phd_call_sources", "version": 1,
        "sources": [source(i) for i in range(3)],
    }
    validate_sources(config)
    import pytest

    with pytest.raises(ValueError):
        validate_sources({**config, "sources": config["sources"][:2]})
    with pytest.raises(ValueError):
        validate_sources({**config, "sources": [
            source(0), source(1), source(2, institution="School B"),
        ]})
    with pytest.raises(ValueError):
        validate_sources({**config, "sources": [
            source(0, count=True), source(1), source(2),
        ]})


def test_same_host_general_phd_index_link_is_checked_without_subject_in_label():
    from tools.update_official_calls import discover_links

    root = {
        "id": "some-index", "institution": "University of Reading",
        "country_code": "UK", "mode": "index",
        "url": "https://www.reading.ac.uk/doctoral-researcher-college/news",
    }
    html = """<h1>Funding announcements</h1>
    <a href="/doctoral-researcher-college/phd-scholarships-2027">
       PhD Scholarships 2027</a>
    <a href="https://external.example/phd-scholarships-2027">
       PhD Scholarships in Economics</a>"""
    assert discover_links(html, root) == [
        "https://www.reading.ac.uk/doctoral-researcher-college/phd-scholarships-2027",
    ]


def test_supported_html_and_unreadable_document_calls_have_separate_health_counts(tmp_path):
    from tools.update_official_calls import refresh_sources

    index = {
        "id": "university-index", "institution": "University of Reading",
        "country_code": "UK", "mode": "index",
        "url": "https://www.reading.ac.uk/doctoral-researcher-college/news",
    }
    html = """<h1>University funding calls</h1>
    <a href="/media/economics-phd-scholarship-2027.pdf">
       Economics PhD Scholarship 2027 PDF</a>
    <a href="/media/economics-phd-fellowship-2027.docx">
       Economics PhD Fellowship 2027 Word document</a>
    <a href="https://unrelated.example/phd-fellowship.pdf">
       Economics PhD Fellowship 2027</a>"""
    catalog = refresh_sources(
        {"kind": "official_phd_call_sources", "version": 1, "sources": [index]},
        {"kind": "official_phd_call_observations", "version": 1,
         "sources": [], "calls": []},
        now=NOW, fetcher=lambda url: {"status": "ok", "html": html},
    )
    assert catalog["calls"] == []
    assert catalog["sources"][0]["unsupported_documents"] == 2
    assert catalog["sources"][0]["index_empty"] is True
    source = tmp_path / "official_calls.json"
    ledger = tmp_path / "ledger.json"
    source.write_text(json.dumps(catalog))
    health = official_calls_health(source, ledger, now=NOW)
    assert health["empty_indexes"] == 1
    assert health["unsupported_documents"] == 2
    assert health["status"] == "degraded"


def test_malformed_group_metadata_never_degrades_to_a_single_post(tmp_path):
    row = _henley("accounting", "Accounting PhD Opportunities")
    row["posting_group"] = "$not-approved group"
    row["posting_group_expected"] = 5
    count, telegram, ledger, _ = _publish(tmp_path, [row])
    assert count == 0
    telegram.send_message.assert_not_called()
    assert not ledger.exists()


def test_duplicate_official_urls_in_registry_are_rejected():
    import pytest

    from tools.update_official_calls import validate_sources

    sources = [{
        "id": f"source-{number}", "institution": "University of Reading",
        "country_code": "UK", "mode": "detail",
        "url": READING,
    } for number in range(2)]
    with pytest.raises(ValueError):
        validate_sources({
            "kind": "official_phd_call_sources", "version": 1,
            "sources": sources,
        })


def test_home_only_bursary_eligibility_is_evidenced_and_visible(tmp_path):
    source = {
        "id": "reading-home-phd-bursaries",
        "institution": "University of Reading",
        "country_code": "UK", "mode": "detail", "url": READING,
        "subject_scope": "multidisciplinary",
    }
    html = """<h1>University of Reading PhD Home fee Bursaries</h1>
    <p>New applicants intending to commence full-time PhD study in September 2027.
    PhD tuition fees at the Home rate for up to four years.</p>
    <p>The bursaries are open to Home students only.</p>
    <h2>Deadline for applications</h2>
    <p>The deadline by which to apply is 30th April 2027.</p>"""
    row = extract_call(html, url=READING, source=source, now=NOW)
    assert row["status"] == "verified"
    assert row["eligibility_scope"] == "home_only"
    assert row["funding_scope"] == "home_rate_tuition"
    count, telegram, _, _ = _publish(tmp_path, [row])
    assert count == 1
    message = telegram.send_message.call_args.kwargs["html"]
    assert "Home-fee applicants only" in message
    assert "Home-rate PhD tuition" in message
    assert "stipend guaranteed" not in message

    no_evidence = {**row, "eligibility_scope": None, "funding_scope": None}
    separate = tmp_path / "no_evidence"
    separate.mkdir()
    count2, tg2, _, _ = _publish(separate, [no_evidence])
    assert count2 == 1
    assert "Home-fee applicants only" not in tg2.send_message.call_args.kwargs["html"]


def test_telegram_error_attempts_are_bounded_even_when_none_succeed(tmp_path):
    from predoc_pipeline.publish.telegram import TelegramError

    rows = [
        _henley(f"separate-{n}", f"Department {n} PhD Opportunities",
                posting_group=None)
        for n in range(7)
    ]
    telegram = Mock()
    telegram.send_message.side_effect = TelegramError(
        "upstream service unavailable", status=503, permanent=False, uncertain=False,
    )
    count, _, ledger, _ = _publish(
        tmp_path, rows, telegram=telegram, reserve_intent=Mock(),
    )
    assert count == 0
    # max_messages=2 must limit actual Telegram API requests, not just successes.
    assert telegram.send_message.call_count == 2
    assert len(json.loads(ledger.read_text())["deliveries"]) == 2


def test_zero_new_index_links_are_visible_despite_prior_call_rechecks():
    from tools.update_official_calls import refresh_sources

    source = {
        "id": "henley-index", "institution": "Henley Business School",
        "country_code": "UK", "mode": "index", "url": HENLEY_ROOT + "all-phds",
    }
    previous = _henley(
        "accounting", "Accounting PhD Opportunities", posting_group=None,
    )
    previous["source_id"] = source["id"]
    article = """<h1>Accounting PhD Studentships</h1>
    <p>Accounting PhD studentship funding is available.</p>
    <p>Studentship applications for the 2027/28 academic year are now open
    and will close on 21 February 2027.</p>"""
    pages = {
        source["url"]: {"status": "ok", "html": "<h1>Latest news</h1>No links"},
        previous["official_url"]: {"status": "ok", "html": article},
    }
    result = refresh_sources(
        {"kind": "official_phd_call_sources", "version": 1, "sources": [source]},
        _catalog(previous), now=NOW, fetcher=lambda url: pages[url],
    )
    summary = result["sources"][0]
    assert summary["status"] == "ok"
    assert summary["index_empty"] is True
    assert summary["discovered_links"] == 0
    assert summary["rechecked_links"] == 1
    assert summary["candidate_count"] == 1
    assert result["calls"][0]["status"] == "verified"


def test_explicitly_closed_current_funding_cycle_cannot_verify():
    source = {
        "id": "henley-closed", "institution": "Henley Business School",
        "country_code": "UK", "mode": "detail", "url": HENLEY_ROOT + "closed",
    }
    html = """<h1>Accounting PhD Studentships 2027</h1>
    <p>PhD funding in Accounting.</p>
    <p>Studentship applications for the 2027/28 academic year are now closed.
    Studentship applications closed on 21 February 2027.</p>"""
    call = extract_call(html, url=source["url"], source=source, now=NOW)
    assert call["status"] == "closed"
    assert eligible_calls(_catalog(call), now=NOW) == []


def test_explicitly_closed_scholarship_without_academic_year_is_not_published():
    source = {
        "id": "ieb-closed", "institution": "Barcelona Institute of Economics (IEB)",
        "country_code": "ES", "mode": "detail",
        "url": "https://ieb.ub.edu/en/phd-scholarship-in-economics-2027/",
    }
    html = """<h1>PhD Scholarship in Economics 2027</h1>
    <p>The scholarship application window is now closed.</p>
    <p>Interested candidates must complete both steps before 11 December 2026.</p>
    <footer>C/ John M. Keynes 1-11, 08034 Barcelona; Tel. +34 93 403 46 46.</footer>"""
    call = extract_call(html, url=source["url"], source=source, now=NOW)
    assert call["status"] == "closed"
    assert eligible_calls(_catalog(call), now=NOW) == []


def test_previous_closed_cycle_does_not_block_current_open_funding():
    source = {
        "id": "henley-accounting", "institution": "Henley Business School",
        "country_code": "UK", "mode": "detail",
        "url": HENLEY_ROOT + "accounting-and-financial-management",
        "title": "Finance and Accounting PhD Studentships",
    }
    html = """<h1>Accounting PhD Opportunities</h1>
    <p>PhD funding in Accounting.</p>
    <p>Studentship applications for the 2026/27 academic year are now closed.</p>
    <p>Studentship applications for the 2027/28 academic year are now open
    and will close on 21 February 2027.</p>"""
    call = extract_call(html, url=source["url"], source=source, now=NOW)
    assert call["status"] == "verified"
    assert call["intake_year"] == 2027


def test_telegram_rate_limited_batch_stops_after_first_rejection(tmp_path):
    from predoc_pipeline.publish.telegram import TelegramError

    rows = [
        _henley(f"throttled-{n}", f"Department {n} PhD Opportunities",
                posting_group=None)
        for n in range(5)
    ]
    telegram = Mock()
    telegram.send_message.side_effect = TelegramError(
        "Bot API retry-after", status=429, permanent=False, uncertain=False,
    )
    result, _, ledger, _ = _publish(
        tmp_path, rows, telegram=telegram, reserve_intent=Mock(),
    )
    assert result == 0
    assert telegram.send_message.call_count == 1
    # The rejected attempt remains reserved, and the other calls stay untouched.
    assert len(json.loads(ledger.read_text())["deliveries"]) == 1


def test_invalid_official_call_catalogue_never_reports_healthy(tmp_path):
    catalog = tmp_path / "catalog.json"
    ledger = tmp_path / "ledger.json"
    catalog.write_text(json.dumps({
        "kind": "tampered_observation_type", "version": 1,
        "sources": [{"status": "ok"}], "calls": [],
    }), encoding="utf-8")
    health = official_calls_health(catalog, ledger, now=NOW)
    assert health["status"] == "unavailable"
    assert health["eligible"] is None


def test_watchdog_does_not_dispatch_calls_the_publisher_rejects():
    examples = [
        {"recommended_admission_iso": "2027-09-01"},
        {"recommended_admission_iso": "2027-02-32"},
        {"institution": "X"},
        {"intake_year": True},
    ]
    runs = [{
        "name": "predoc-pipeline", "head_branch": "main",
        "status": "completed", "created_at": "2026-11-20T06:00:00Z",
    }]
    for overrides in examples:
        row = _henley(
            "accounting", "Accounting PhD Opportunities", posting_group=None,
        )
        row.update(overrides)
        assert eligible_calls(_catalog(row), now=NOW) == []
        decision = evaluate_official_calls_trigger(
            _catalog(row), {"version": 1, "deliveries": {}}, runs, now=NOW,
        )
        assert not decision.dispatch, overrides


def test_generic_current_closure_after_previous_closed_round_is_not_published():
    source = {
        "id": "henley-closed-funding", "institution": "Henley Business School",
        "country_code": "UK", "mode": "detail",
        "url": HENLEY_ROOT + "closed-funding",
    }
    html = """<h1>Accounting PhD Studentships 2027</h1>
    <p>Accounting PhD funding.</p>
    <p>Studentship applications for the 2026/27 academic year are now closed.</p>
    <p>The scholarship application window is now closed.</p>
    <p>Studentship applications closed on 21 February 2027.</p>"""
    row = extract_call(html, url=source["url"], source=source, now=NOW)
    assert row["status"] == "closed"
    assert eligible_calls(_catalog(row), now=NOW) == []
