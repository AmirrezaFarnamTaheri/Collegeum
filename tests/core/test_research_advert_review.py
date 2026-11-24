"""A review target cannot promote unavailable or duplicated advert evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tools.audit_research_adverts import audit_review

NOW = datetime(2026, 11, 24, 18, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


def review() -> dict:
    rows = []
    for index in range(251):
        url = f"https://careers.example.edu/jobs/{index}"
        rows.append({
            "advert_id": f"example:{index}", "url": url, "aliases": [],
            "title": f"Research assistant {index}", "institution": "Example University",
            "source": "example_research", "identity_basis": "Exact employer requisition URL",
            "discovered_from": "A committed source discovery manifest",
            "checked_at": "2026-11-24T17:00:00Z", "outcome": "access_unavailable",
            "eligibility": "not_assessed", "reason": "Robots policy was unavailable",
            "body_evidence": False, "identity_matched": False,
            "evidence": {
                "kind": "access_decision", "url": url, "status": None,
                "request_sent": False, "checked_at": "2026-11-24T17:00:00Z",
                "access_reason": "robots_unavailable",
                "policy_evidence": {
                    "url": "https://careers.example.edu/robots.txt", "status": 503,
                    "checked_at": "2026-11-24T16:59:00Z",
                },
            },
        })
    return {
        "kind": "research_advert_review", "version": 1, "target": 251,
        "reviewed_at": "2026-11-24T17:30:00Z", "selection_rule": "Fixed requisition cohort",
        "adverts": rows,
    }


CAPTURE = (
    b"<h1>Research assistant in economics</h1><p>"
    b"Research assistant in economics. Apply by December 2026. "
    + b"The role analyses economic data and supports faculty research. " * 10
    + b"</p>"
)


def add_body(row: dict, content: bytes = CAPTURE) -> None:
    row.update(
        outcome="readable_advert", body_evidence=True, identity_matched=True,
        body_characters=500,
        evidence_excerpt="Research assistant in economics. Apply by December 2026.",
        reason="Primary requisition and substantive advert body match the candidate.",
    )
    row["evidence"] = {
        "kind": "page_response", "url": row["url"], "final_url": row["url"],
        "checked_at": "2026-11-24T16:59:00Z", "status": 200, "request_sent": True,
        "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
    }


class ResearchAdvertReviewTests(unittest.TestCase):
    def test_committed_review_has_251_distinct_completed_observations(self):
        path = ROOT / "review/2026-11-24/research-adverts-251.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        # This is a dated research record, not a claim of current availability.
        result = audit_review(document, now=datetime(2026, 11, 25, tzinfo=UTC))
        self.assertEqual(result["metadata_issues"], [])
        self.assertTrue(result["summary"]["target_met"], [
            row for row in result["observations"] if row["issues"]
        ])
        self.assertEqual(result["summary"]["distinct_research_adverts_checked"], 251)
        self.assertEqual(sum(result["summary"]["outcome_counts"].values()), 251)

    def test_completed_checks_and_body_evidence_are_separate(self):
        document = review()
        add_body(document["adverts"][0])
        original = copy.deepcopy(document)
        result = audit_review(document, now=NOW)
        self.assertEqual(document, original)
        self.assertEqual(result["summary"]["distinct_research_adverts_checked"], 251)
        self.assertTrue(result["summary"]["target_met"])
        self.assertEqual(result["summary"]["adverts_with_body_evidence"], 1)
        self.assertFalse(result["summary"]["all_adverts_have_body_evidence"])
        self.assertEqual(result["summary"]["outcome_counts"],
                         {"access_unavailable": 250, "readable_advert": 1})
        self.assertEqual(result["summary"]["raw_capture_hashes_verified"], 0)
        self.assertNotIn("open_adverts", result["summary"])

    def test_claimed_counts_do_not_complete_a_partial_review(self):
        document = review()
        document["summary"] = {"distinct_research_adverts_checked": 251, "target_met": True}
        document["adverts"][0]["outcome"] = "pending"
        result = audit_review(document, now=NOW)
        self.assertFalse(result["summary"]["target_met"])
        self.assertEqual(result["summary"]["distinct_research_adverts_checked"], 250)
        document["adverts"].pop()
        self.assertIn("unexpected_advert_count", audit_review(document, now=NOW)["metadata_issues"])

    def test_same_requisition_alias_or_capture_cannot_pad_the_count(self):
        for kind in ("identity", "alias", "tracking", "capture"):
            with self.subTest(kind=kind):
                document = review()
                first, second = document["adverts"][:2]
                if kind == "identity":
                    second["advert_id"] = first["advert_id"]
                elif kind == "alias":
                    first["aliases"] = [second["url"]]
                elif kind == "tracking":
                    second["url"] = first["url"] + "?utm_source=mirror#details"
                else:
                    add_body(first)
                    add_body(second)
                result = audit_review(document, now=NOW)
                self.assertEqual(result["summary"]["distinct_research_adverts_checked"], 249)
                self.assertFalse(result["summary"]["target_met"])

    def test_common_error_page_does_not_merge_distinct_historical_requisitions(self):
        document = review()
        for row in document["adverts"][:2]:
            add_body(row, b"Shared JavaScript career shell")
            row.update(outcome="unverified_page", body_evidence=False, identity_matched=False)
            row["evidence"]["final_url"] = "https://careers.example.edu/careers"
        result = audit_review(document, now=NOW)
        self.assertTrue(result["summary"]["target_met"])
        self.assertEqual(result["summary"]["adverts_with_body_evidence"], 0)
        self.assertEqual(result["summary"]["outcome_counts"]["unverified_page"], 2)

    def test_unsupported_success_or_closure_and_bad_provenance_fail_closed(self):
        cases = [
            ({"outcome": "readable_advert"}, "advert_outcome_without_body_evidence"),
            ({"eligibility": "collector_eligible"}, "eligible_without_advert_body"),
            ({"outcome": "removed_advert"}, "removed_link_without_http_evidence"),
            ({"body_evidence": 1}, "invalid_body_evidence_flag"),
            ({"checked_at": "2026-11-25T17:00:00Z"}, "invalid_check_timestamp"),
            ({"checked_at": "2026-11-24T17:00:00"}, "invalid_check_timestamp"),
            ({"url": "https://accounts.google.com/signin"}, "invalid_advert_url"),
        ]
        for change, expected in cases:
            with self.subTest(change=change):
                document = review()
                document["adverts"][0].update(change)
                result = audit_review(document, now=NOW)
                self.assertIn(expected, result["observations"][0]["issues"])
                self.assertEqual(result["summary"]["distinct_research_adverts_checked"], 250)
        for evidence_change, expected in (
            ({"policy_evidence": {}}, "invalid_access_policy_evidence"),
            ({"status": 403}, "access_decision_misrepresented_as_response"),
            ({"checked_at": "2026-11-24T17:05:00Z"}, "invalid_evidence_timestamp"),
        ):
            document = review()
            document["adverts"][0]["evidence"].update(evidence_change)
            self.assertIn(expected, audit_review(document, now=NOW)["observations"][0]["issues"])

    def test_raw_capture_verification_detects_tampering_and_escaping_symlinks(self):
        document = review()
        content = CAPTURE
        row = document["adverts"][0]
        add_body(row, content)
        name = hashlib.sha256(row["url"].encode()).hexdigest()[:20] + ".html"
        with tempfile.TemporaryDirectory() as folder:
            capture_dir = Path(folder) / "captures"
            capture_dir.mkdir()
            capture = capture_dir / name
            capture.write_bytes(content)
            result = audit_review(document, now=NOW, capture_dir=capture_dir)
            self.assertTrue(result["summary"]["target_met"])
            self.assertEqual(result["summary"]["raw_capture_hashes_verified"], 1)
            capture.write_bytes(b"Replaced response")
            result = audit_review(document, now=NOW, capture_dir=capture_dir)
            self.assertIn("raw_capture_mismatch", result["observations"][0]["issues"])
            outside = Path(folder) / "outside"
            outside.write_bytes(content)
            capture.unlink()
            capture.symlink_to(outside)
            result = audit_review(document, now=NOW, capture_dir=capture_dir)
            self.assertIn("missing_raw_capture", result["observations"][0]["issues"])

    def test_evidence_must_belong_to_the_advert_and_its_access_policy(self):
        document = review()
        document["adverts"][0]["evidence"]["url"] = "https://unrelated.example.org/jobs/1"
        result = audit_review(document, now=NOW)
        self.assertIn("evidence_not_bound_to_advert_or_reviewed_alias",
                      result["observations"][0]["issues"])
        document = review()
        document["adverts"][0]["evidence"]["policy_evidence"]["url"] = (
            "https://unrelated.example.org/robots.txt"
        )
        self.assertIn("access_policy_for_unrelated_origin",
                      audit_review(document, now=NOW)["observations"][0]["issues"])

    def test_valid_hash_does_not_make_an_access_page_a_readable_advert(self):
        document = review()
        row = document["adverts"][0]
        gate = b"<h1>Access denied</h1><p>Please sign in.</p>"
        add_body(row, gate)
        name = hashlib.sha256(row["url"].encode()).hexdigest()[:20] + ".html"
        with tempfile.TemporaryDirectory() as folder:
            capture_dir = Path(folder)
            (capture_dir / name).write_bytes(gate)
            result = audit_review(document, now=NOW, capture_dir=capture_dir)
        self.assertIn("body_excerpt_absent_from_raw_capture", result["observations"][0]["issues"])
        self.assertIn("body_size_not_supported_by_raw_capture", result["observations"][0]["issues"])
        self.assertEqual(result["summary"]["adverts_with_body_evidence"], 0)
        row["outcome"] = "unverified_page"
        self.assertIn("body_claim_conflicts_with_outcome",
                      audit_review(document, now=NOW)["observations"][0]["issues"])

    def test_malformed_enum_values_are_reported_without_crashing(self):
        for field in ("outcome", "eligibility"):
            for malformed in ({}, []):
                with self.subTest(field=field, value=malformed):
                    document = review()
                    document["adverts"][0][field] = malformed
                    result = audit_review(document, now=NOW)
                    self.assertEqual(result["summary"]["invalid_records"], 1)

    def test_read_only_cli_runs_without_site_packages_and_fails_stricter_body_target(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "review.json"
            path.write_text(json.dumps(review()), encoding="utf-8")
            before = path.read_bytes()
            command = [sys.executable, "-S", str(ROOT / "tools/audit_research_adverts.py"),
                       "--review", str(path), "--now", NOW.isoformat(), "--json"]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(json.loads(completed.stdout)["summary"]["target_met"])
            bodies = subprocess.run(command + ["--require-all-bodies"], capture_output=True,
                                    text=True, check=False)
            self.assertEqual(bodies.returncode, 1, bodies.stderr)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
