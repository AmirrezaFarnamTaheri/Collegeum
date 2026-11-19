"""A completed official-source refresh must not strand publishable programmes."""
from datetime import UTC, datetime, timedelta

from tools.ingestion_watchdog import evaluate_admissions_trigger

NOW = datetime(2026, 11, 19, 19, 30, tzinfo=UTC)
BASE = "https://berlinschoolofeconomics.de/phd-program/application"


def catalog(status="verified"):
    return {
        "kind": "economics_phd_admissions_observations",
        "scope": "official_programme_sources_only",
        "source": {"deadline_values_reused": False},
        "programmes": [{
            "institution": "Berlin School of Economics", "country_code": "DE",
            "status": status, "checked_at": "2026-11-19T18:22:00Z",
            "deadline_iso": "2027-01-15", "official_programme_url": BASE,
            "evidence_url": BASE,
            "evidence_excerpt": "Economics PhD application deadline January 15, 2027",
        }],
    }


def pipeline_run(when, status="completed"):
    return [{"name": "predoc-pipeline", "head_branch": "main",
             "created_at": when, "status": status}]


def test_new_verified_unpublished_admission_dispatches_after_refresh():
    result = evaluate_admissions_trigger(
        catalog(), {"version": 1, "deliveries": {}},
        pipeline_run("2026-11-19T12:49:00Z"), now=NOW)
    assert result.dispatch
    assert result.reason == "new-verified-admissions-awaiting-publisher"


def test_latest_pipeline_or_running_pipeline_suppresses_retry():
    for runs in (
        pipeline_run("2026-11-19T18:23:00Z"),
        pipeline_run("2026-11-19T12:49:00Z", "in_progress"),
        [],
    ):
        assert not evaluate_admissions_trigger(
            catalog(), {"version": 1, "deliveries": {}}, runs, now=NOW).dispatch


def test_blocked_or_unverified_programmes_never_trigger():
    for status in ("robots_unavailable", "unverified", "fetch_failed"):
        assert not evaluate_admissions_trigger(
            catalog(status), {"version": 1, "deliveries": {}},
            pipeline_run("2026-11-19T12:49:00Z"), now=NOW).dispatch


def test_authorized_reissue_is_one_time_and_requires_newer_authorization():
    import hashlib
    key = hashlib.sha256(b"DE|berlin school of economics").hexdigest()[:32]
    ledger = {"version": 1, "deliveries": {key: {
        "state": "reissue_authorized",
        "prior_message_id": 129,
        "reissue_authorized_at": "2026-11-19T19:24:00Z",
    }}}
    assert evaluate_admissions_trigger(
        catalog(), ledger, pipeline_run("2026-11-19T12:49:00Z"), now=NOW).dispatch
    assert not evaluate_admissions_trigger(
        catalog(), ledger, pipeline_run("2026-11-19T19:25:00Z"), now=NOW).dispatch
    ledger["deliveries"][key]["state"] = "confirmed"
    assert not evaluate_admissions_trigger(
        catalog(), ledger, pipeline_run("2026-11-19T12:49:00Z"), now=NOW).dispatch


def test_untrusted_catalogue_or_evidence_cannot_request_dispatch():
    catalog_bad = catalog()
    catalog_bad["programmes"][0]["evidence_url"] = "https://external.example/phd"
    assert not evaluate_admissions_trigger(
        catalog_bad, {"version": 1, "deliveries": {}},
        pipeline_run("2026-11-19T12:49:00Z"), now=NOW).dispatch
    assert not evaluate_admissions_trigger(
        catalog(), {"version": 4, "deliveries": {}},
        pipeline_run("2026-11-19T12:49:00Z"), now=NOW).dispatch
