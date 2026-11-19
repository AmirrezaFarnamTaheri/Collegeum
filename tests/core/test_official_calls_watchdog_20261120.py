"""New official scholarship observations must wake the safe existing publisher."""
from datetime import UTC, datetime, timedelta

from tools.ingestion_watchdog import evaluate_official_calls_trigger

NOW = datetime(2026, 11, 20, 20, tzinfo=UTC)
OFFICIAL = "https://www.henley.ac.uk/study/phds/accounting-and-financial-management"


def row():
    return {
        "source_id": "henley-accounting", "institution": "Henley Business School",
        "country_code": "UK", "kind": "phd_studentship",
        "title": "Accounting PhD Opportunities",
        "status": "verified", "intake_year": 2027,
        "official_url": OFFICIAL, "evidence_url": OFFICIAL,
        "evidence_excerpt": "Studentship applications now open and will close on 21 February 2027",
        "deadline_iso": "2027-02-21", "deadline_kind": "funding",
        "location_evidence_url": OFFICIAL,
        "location_evidence": "UK: official national institutional domain henley.ac.uk",
        "checked_at": NOW.isoformat(),
    }


def run(created, status="completed"):
    return {"name": "predoc-pipeline", "head_branch": "main",
            "created_at": created, "status": status}


def test_new_verified_official_call_triggers_one_guarded_recovery():
    catalog = {"kind": "official_phd_call_observations", "version": 1, "calls": [row()]}
    ledger = {"version": 1, "deliveries": {}}
    runs = [run((NOW - timedelta(hours=3)).isoformat())]
    decision = evaluate_official_calls_trigger(catalog, ledger, runs, now=NOW)
    assert decision.dispatch
    assert decision.reason == "new-official-calls-awaiting-publisher"


def test_newer_or_active_pipeline_does_not_dispatch_duplicate():
    catalog = {"kind": "official_phd_call_observations", "version": 1, "calls": [row()]}
    ledger = {"version": 1, "deliveries": {}}
    for runs in (
        [run((NOW + timedelta(seconds=1)).isoformat())],
        [run((NOW - timedelta(hours=3)).isoformat(), "in_progress")],
        [],
    ):
        assert not evaluate_official_calls_trigger(catalog, ledger, runs, now=NOW).dispatch


def test_blocked_or_unproven_location_never_triggers():
    catalog = {"kind": "official_phd_call_observations", "version": 1, "calls": [row()]}
    ledger = {"version": 1, "deliveries": {}}
    runs = [run((NOW - timedelta(hours=3)).isoformat())]
    for change in ({"status": "robots_unavailable"}, {"country_code": "FR"},
                   {"evidence_url": "https://fake.example/phd"},
                   {"location_evidence": ""}):
        changed = {**row(), **change}
        assert not evaluate_official_calls_trigger(
            {**catalog, "calls": [changed]}, ledger, runs, now=NOW,
        ).dispatch


def test_confirmed_or_uncertain_receipt_cannot_dispatch_again():
    import hashlib

    catalog = {"kind": "official_phd_call_observations", "version": 1, "calls": [row()]}
    key = hashlib.sha256(
        b"henley.ac.uk|/study/phds/accounting-and-financial-management|2027"
    ).hexdigest()[:32]
    runs = [run((NOW - timedelta(hours=3)).isoformat())]
    for state in ("confirmed", "uncertain", "pending", "permanent_failure"):
        ledger = {"version": 1, "deliveries": {key: {"state": state}}}
        assert not evaluate_official_calls_trigger(
            catalog, ledger, runs, now=NOW,
        ).dispatch
