"""Document-only scholarship candidates must remain reviewable and nonpublishable."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from predoc_pipeline.core.official_call_rules import call_key
from tools.official_document_review_journal import load_review_records, record_review
from tools.official_document_triage import build_document_triage

PDF = "https://ieb.ub.edu/wp-content/uploads/2026/11/IEB-PhD-Scholarship-2027-28.pdf"
DOC = "https://ieb.ub.edu/wp-content/uploads/2026/11/legacy-phd-call.doc"
DOCX = "https://ieb.ub.edu/wp-content/uploads/2026/11/new-phd-call.docx"
HTML = "https://ieb.ub.edu/en/phd-scholarship-in-economics-2027/"
INDEX = "https://ieb.ub.edu/convocatorias/"
INDEX_2 = "https://ieb.ub.edu/en/call-for-application/"
REGISTRY = {
    "kind": "official_phd_call_sources", "version": 1,
    "sources": [
        {
            "id": "ieb-document-index", "institution": "Barcelona Institute of Economics (IEB)",
            "country_code": "ES", "mode": "index", "url": INDEX,
            "approved_documents": [
                {"url": PDF, "title": "PhD Scholarship in Economics",
                 "institution_marker": "Barcelona Institute of Economics",
                 "canonical_html_url": HTML},
            ],
        },
        {
            "id": "ieb-second-index", "institution": "Barcelona Institute of Economics (IEB)",
            "country_code": "ES", "mode": "index", "url": INDEX_2,
        },
    ],
}
CATALOG = {
    "kind": "official_phd_call_observations",
    "version": 1,
    "generated_at": "2026-11-21T11:00:00Z",
    "calls": [],
    "sources": [
        {
            "id": "ieb-document-index", "status": "ok", "mode": "index",
            "index_url": INDEX, "institution": "Barcelona Institute of Economics (IEB)",
            "document_candidates": [PDF, DOC, DOCX],
        },
        {
            "id": "ieb-second-index", "status": "ok", "mode": "index",
            "index_url": INDEX_2, "institution": "Barcelona Institute of Economics (IEB)",
            "document_candidates": [PDF],
        },
    ],
}
NOW = datetime(2026, 11, 21, tzinfo=UTC)


def reviewed(*, digest: str = "a" * 64, deadline: str = "2026-12-11"):
    return {
        "status": "document_review_only", "source_id": "ieb-document-index",
        "official_url": PDF, "reviewed_at": "2026-11-21T11:00:00Z",
        "document_sha256": digest,
        "canonical_html_url": HTML,
        "title": "PhD Scholarship in Economics",
        "institution": "Barcelona Institute of Economics (IEB)",
        "country_code": "ES", "kind": "phd_scholarship",
        "intake_year": 2027, "deadline_iso": deadline,
        "deadline_kind": "scholarship",
        "evidence_excerpt": "Interested candidates must complete both steps by 11 December 2026.",
        "method": "live_fetch", "document_format": "pdf", "reason": None,
        "automatic_publication": False,
    }


def test_document_triage_deduplicates_indexes_and_keeps_legacy_doc_held():
    queue = build_document_triage(CATALOG, REGISTRY, {}, [])
    assert queue["kind"] == "official_phd_document_triage"
    assert queue["version"] == 1
    assert queue["generated_at"] == CATALOG["generated_at"]
    assert len(queue["documents"]) == 3
    pdf = next(row for row in queue["documents"] if row["official_url"] == PDF)
    assert pdf["source_ids"] == ["ieb-document-index", "ieb-second-index"]
    assert pdf["approved"] is True
    assert pdf["next_action"] == "review_required"
    assert pdf["canonical_html_url"] == HTML
    legacy = next(row for row in queue["documents"] if row["official_url"] == DOC)
    assert legacy["next_action"] == "unsupported_legacy_doc"
    assert legacy["approved"] is False
    docx = next(row for row in queue["documents"] if row["official_url"] == DOCX)
    assert docx["next_action"] == "approval_required"
    assert all(row["automatic_publication"] is False for row in queue["documents"])


def test_verified_document_review_never_claims_delivery_without_same_cycle_receipt():
    review = reviewed()
    old = {
        "state": "confirmed", "message_id": 133, "official_url": HTML,
        "institution": "Barcelona Institute of Economics (IEB)",
        "intake_year": 2027, "deadline_iso": "2026-12-11",
        "title": "PhD Scholarship in Economics 2027",
    }
    queue = build_document_triage(CATALOG, REGISTRY, {call_key(old): old}, [review])
    pdf = next(item for item in queue["documents"] if item["official_url"] == PDF)
    assert pdf["next_action"] == "already_delivered_same_cycle"
    assert pdf["prior_message_id"] == 133
    assert pdf["review_status"] == "document_review_only"
    assert pdf["deadline_iso"] == "2026-12-11"
    assert pdf["evidence_excerpt"] == review["evidence_excerpt"]
    # Same canonical HTML in a different annual funding cycle is not a duplicate.
    previous_year = {**old, "intake_year": 2026, "deadline_iso": "2025-12-11"}
    changed = build_document_triage(CATALOG, REGISTRY, {"b" * 32: previous_year},
                                    [review])
    pdf = next(item for item in changed["documents"] if item["official_url"] == PDF)
    assert pdf["next_action"] == "review_complete_no_delivery"
    assert pdf["prior_message_id"] is None


def test_audit_preserves_independent_deadline_evidence_and_revisions(tmp_path):
    target = tmp_path / "review.json"
    assert record_review(target, reviewed(), registry=REGISTRY, method="live_fetch")
    rows = load_review_records(target, registry=REGISTRY)
    assert rows[0]["evidence_excerpt"] == reviewed()["evidence_excerpt"]
    assert rows[0]["deadline_iso"] == "2026-12-11"
    assert rows[0]["intake_year"] == 2027
    assert rows[0]["institution"] == "Barcelona Institute of Economics (IEB)"
    assert record_review(target, reviewed(digest="b" * 64),
                         registry=REGISTRY, method="live_fetch")
    assert len(load_review_records(target, registry=REGISTRY)) == 2


def test_successful_review_audit_rejects_missing_or_contradictory_evidence(tmp_path):
    target = tmp_path / "review.json"
    for changes in (
        {"evidence_excerpt": ""},
        {"evidence_excerpt": "An unrelated academic year only."},
        {"evidence_excerpt": "Email someone@example.org by 11 December 2026."},
        {"deadline_iso": "2026-02-30"},
        {"deadline_iso": "2027-01-15"},
        {"intake_year": True},
        {"institution": "Different University"},
        {"title": "Unrelated award"},
        {"country_code": "XX"},
    ):
        with pytest.raises(ValueError):
            record_review(target, {**reviewed(), **changes},
                          registry=REGISTRY, method="live_fetch")
        assert not target.exists()


def test_document_triage_refuses_untrusted_source_urls_and_inconsistent_approvals():
    tampered = {
        **CATALOG,
        "sources": [
            {**CATALOG["sources"][0],
             "document_candidates": [PDF, "http://evil.example/award.pdf"]},
        ],
    }
    with pytest.raises(ValueError):
        build_document_triage(tampered, REGISTRY, {}, [])
    conflicting = {
        **REGISTRY, "sources": [
            REGISTRY["sources"][0],
            {**REGISTRY["sources"][1], "approved_documents": [
                {**REGISTRY["sources"][0]["approved_documents"][0],
                 "canonical_html_url": "https://ieb.ub.edu/en/a-different-phd-call/"},
            ]},
        ],
    }
    result = build_document_triage(CATALOG, conflicting, {}, [])
    pdf = next(x for x in result["documents"] if x["official_url"] == PDF)
    assert pdf["approved"] is False
    assert pdf["next_action"] == "conflicting_approvals"


def test_pending_or_uncertain_prior_attempt_never_looks_unsent_to_operator():
    for state in ("pending", "uncertain", "retry_held", "permanent_failure"):
        old = {
            "state": state, "official_url": HTML,
            "institution": "Barcelona Institute of Economics (IEB)",
            "intake_year": 2027, "deadline_iso": "2026-12-11",
        }
        queue = build_document_triage(CATALOG, REGISTRY, {"a" * 32: old},
                                      [reviewed()])
        pdf = next(x for x in queue["documents"] if x["official_url"] == PDF)
        assert pdf["next_action"] == "prior_attempt_requires_reconciliation"
        assert pdf["prior_message_id"] is None


def test_old_year_receipt_with_identical_cutoff_requires_reconciliation():
    # Earlier source-year parsing could store the same 2027 round as 2026.
    prior = {
        "state": "confirmed", "message_id": 133, "official_url": HTML,
        "institution": "Barcelona Institute of Economics (IEB)",
        "intake_year": 2026, "deadline_iso": "2026-12-11",
    }
    queue = build_document_triage(CATALOG, REGISTRY, {"b" * 32: prior},
                                  [reviewed()])
    pdf = next(x for x in queue["documents"] if x["official_url"] == PDF)
    assert pdf["next_action"] == "prior_attempt_requires_reconciliation"
    assert pdf["prior_message_id"] is None


def test_forged_receipt_key_cannot_prove_document_was_delivered():
    old = {
        "state": "confirmed", "message_id": 133, "official_url": HTML,
        "institution": "Barcelona Institute of Economics (IEB)",
        "intake_year": 2027, "deadline_iso": "2026-12-11",
        "title": "PhD Scholarship in Economics 2027",
    }
    assert call_key(old) != "a" * 32
    result = build_document_triage(CATALOG, REGISTRY, {"a" * 32: old}, [reviewed()])
    pdf = next(x for x in result["documents"] if x["official_url"] == PDF)
    assert pdf["next_action"] == "prior_attempt_requires_reconciliation"
    assert pdf["prior_message_id"] is None


def test_distinct_scholarship_same_url_cycle_is_not_marked_delivered():
    other = {
        "state": "confirmed", "message_id": 134, "official_url": HTML,
        "institution": "Barcelona Institute of Economics (IEB)",
        "intake_year": 2027, "deadline_iso": "2026-12-11",
        "title": "PhD Fellowship in Energy Economics 2027",
    }
    result = build_document_triage(CATALOG, REGISTRY, {call_key(other): other},
                                   [reviewed()])
    pdf = next(x for x in result["documents"] if x["official_url"] == PDF)
    assert pdf["next_action"] == "prior_attempt_requires_reconciliation"
    assert pdf["prior_message_id"] is None

def test_repeated_policy_block_and_review_transition_are_idempotent(tmp_path):
    target = tmp_path / "review.json"
    blocked = {
        "status": "robots_disallowed", "reason": "robots_disallowed",
        "source_id": "ieb-document-index", "official_url": PDF,
        "reviewed_at": "2026-11-21T11:02:00Z",
    }
    assert record_review(target, blocked, registry=REGISTRY, method="live_fetch")
    # A blocked request has no extracted title, deadline or evidence excerpt.
    # Repeating an unchanged policy block must be a no-op, never KeyError.
    assert record_review(
        target, {**blocked, "reviewed_at": "2026-11-21T11:03:00Z"},
        registry=REGISTRY, method="live_fetch",
    ) is False
    assert len(load_review_records(target, registry=REGISTRY)) == 1
    assert record_review(target, reviewed(), registry=REGISTRY, method="live_fetch")
    # Repeated identical success has no duplicate audit row.
    assert record_review(
        target, {**reviewed(), "reviewed_at": "2026-11-21T11:04:00Z"},
        registry=REGISTRY, method="live_fetch",
    ) is False
    assert len(load_review_records(target, registry=REGISTRY)) == 2
    # A newly blocked retrieval must not destroy the previous proof hash.
    assert record_review(target, blocked, registry=REGISTRY, method="live_fetch")
    rows = load_review_records(target, registry=REGISTRY)
    assert [x["status"] for x in rows] == [
        "robots_disallowed", "document_review_only", "robots_disallowed",
    ]
    assert rows[1]["document_sha256"] == "a" * 64


def test_journal_rejects_deadline_lookalikes_and_ambiguous_excerpt(tmp_path):
    target = tmp_path / "review.json"
    for excerpt in (
        "Course commenced on 11 December 2026.",
        "Funding allocated 11 December 2026 but not an application cutoff.",
        "Applications are due on 11 December 2026 or 15 January 2027.",
        "Send forms by 11 December 2026 to phone +34 93 123 4567.",
    ):
        with pytest.raises(ValueError):
            record_review(
                target, {**reviewed(), "evidence_excerpt": excerpt},
                registry=REGISTRY, method="live_fetch",
            )
        assert not target.exists()


def test_direct_triage_rejects_forged_or_incomplete_document_reviews():
    for bad in (
        {"document_sha256": None},
        {"method": "background_auto_fetch"},
        {"automatic_publication": True},
        {"canonical_html_url": "https://ieb.ub.edu/en/unrelated-scholarship/"},
        {"deadline_iso": "2027-01-15"},
        {"official_url": "https://untrusted.example/phd.pdf"},
        {"evidence_excerpt": "The degree begins on 11 December 2026."},
    ):
        with pytest.raises(ValueError):
            build_document_triage(
                CATALOG, REGISTRY, {}, [{**reviewed(), **bad}],
            )


def test_direct_triage_rejects_unvalidated_policy_failure_rows():
    blocked = {
        "status": "robots_disallowed", "source_id": "ieb-document-index",
        "official_url": PDF, "reviewed_at": "2026-11-21T11:00:00Z",
        "reason": "robots_disallowed", "method": "live_fetch",
        "document_sha256": None, "document_format": "pdf",
        "canonical_html_url": HTML, "automatic_publication": False,
    }
    assert build_document_triage(CATALOG, REGISTRY, {}, [blocked])["documents"]
    with pytest.raises(ValueError):
        build_document_triage(
            CATALOG, REGISTRY, {}, [{**blocked, "method": "unknown"}],
        )


def test_revised_same_cycle_deadline_never_appears_unsent_to_operator():
    # Institutions correct deadlines after publication. A changed funding
    # cutoff is not proof the earlier Telegram attempt never happened.
    for state in ("confirmed", "pending", "uncertain", "retry_held"):
        previous = {
            "state": state, "message_id": 133, "official_url": HTML,
            "institution": "Barcelona Institute of Economics (IEB)",
            "intake_year": 2027, "deadline_iso": "2026-12-09",
            "title": "PhD Scholarship in Economics 2027",
        }
        key = call_key(previous)
        pdf = next(x for x in build_document_triage(
            CATALOG, REGISTRY, {key: previous}, [reviewed()],
        )["documents"] if x["official_url"] == PDF)
        assert pdf["next_action"] == "prior_attempt_requires_reconciliation"
        assert pdf["prior_message_id"] is None


def test_uncertain_receipt_without_deadline_cannot_look_unsent():
    previous = {
        "state": "uncertain", "official_url": HTML,
        "institution": "Barcelona Institute of Economics (IEB)",
        "intake_year": 2027, "deadline_iso": None,
        "title": "PhD Scholarship in Economics 2027",
    }
    pdf = next(x for x in build_document_triage(
        CATALOG, REGISTRY, {"legacy-unknown": previous}, [reviewed()],
    )["documents"] if x["official_url"] == PDF)
    assert pdf["next_action"] == "prior_attempt_requires_reconciliation"
    assert pdf["prior_message_id"] is None


def test_historical_different_cycle_deadline_remains_new_reviewer_lead():
    previous = {
        "state": "confirmed", "message_id": 95, "official_url": HTML,
        "institution": "Barcelona Institute of Economics (IEB)",
        "intake_year": 2026, "deadline_iso": "2025-12-11",
        "title": "PhD Scholarship in Economics 2026",
    }
    pdf = next(x for x in build_document_triage(
        CATALOG, REGISTRY, {call_key(previous): previous}, [reviewed()],
    )["documents"] if x["official_url"] == PDF)
    assert pdf["next_action"] == "review_complete_no_delivery"


def test_future_dated_review_is_rejected_at_all_validation_entrypoints(tmp_path):
    future = {**reviewed(), "reviewed_at": "2099-01-01T00:00:00Z"}
    with pytest.raises(ValueError):
        build_document_triage(CATALOG, REGISTRY, {}, [future])
    with pytest.raises(ValueError):
        record_review(
            tmp_path / "reviews.json", future, registry=REGISTRY,
            method="live_fetch",
        )
    assert not (tmp_path / "reviews.json").exists()


def test_conflicting_same_time_document_revisions_fail_closed(tmp_path):
    first = reviewed(digest="a" * 64)
    conflicting = reviewed(digest="b" * 64)
    target = tmp_path / "reviews.json"
    assert record_review(target, first, registry=REGISTRY, method="live_fetch")
    # A different body at the same second has no defensible event order.
    with pytest.raises(ValueError):
        record_review(target, conflicting, registry=REGISTRY, method="live_fetch")
    assert len(load_review_records(target, registry=REGISTRY)) == 1
    with pytest.raises(ValueError):
        build_document_triage(CATALOG, REGISTRY, {}, [first, conflicting])


def test_out_of_order_revised_review_does_not_override_newer_audit(tmp_path):
    newer = {**reviewed(digest="b" * 64), "reviewed_at": "2026-11-21T11:10:00Z"}
    older = {**reviewed(digest="a" * 64), "reviewed_at": "2026-11-21T11:00:00Z"}
    path = tmp_path / "reviews.json"
    assert record_review(path, newer, registry=REGISTRY, method="live_fetch")
    with pytest.raises(ValueError):
        record_review(path, older, registry=REGISTRY, method="live_fetch")
    assert [x["document_sha256"] for x in load_review_records(
        path, registry=REGISTRY,
    )] == ["b" * 64]

