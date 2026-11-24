"""Coverage accounting must not turn missing or stale evidence into success."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.audit_phd_admissions import audit_catalogues, main, text_report

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


def catalogues() -> tuple[dict, dict]:
    leads = [
        {
            "institution": f"University {index}", "country_code": "US",
            "official_programme_url": f"https://economics.example.edu/phd/{index}",
            "programme_structure_hint": "PhD only",
        }
        for index in range(251)
    ]
    observations = [dict(row, status="unverified", deadline_iso=None) for row in leads]
    return (
        {"kind": "economics_phd_admissions_seeds", "programmes": leads},
        {
            "kind": "economics_phd_admissions_observations",
            "scope": "official_programme_sources_only",
            "source": {"deadline_values_reused": False},
            "generated_at": "2026-11-24T12:00:00Z",
            "programmes": observations,
        },
    )


def verify(row: dict) -> None:
    row.update(
        status="verified", checked_at="2026-11-24T11:00:00Z",
        deadline_iso="2027-01-15", evidence_url=row["official_programme_url"],
        evidence_excerpt="PhD in Economics application deadline: January 15, 2027.",
        investigated_urls=[row["official_programme_url"]],
    )


class AdmissionsCoverageAuditTests(unittest.TestCase):
    def test_reports_every_programme_and_distinguishes_access_and_evidence_gaps(self):
        seeds, public = catalogues()
        verify(public["programmes"][0])
        for index, status in enumerate((
            "no_explicit_deadline", "robots_unavailable", "fetch_failed",
            "robots_disallowed", "unsafe_redirect", "ambiguous_deadline",
        ), start=1):
            public["programmes"][index].update(
                status=status, checked_at="2026-11-24T11:00:00Z",
            )
        original = copy.deepcopy((seeds, public))
        report = audit_catalogues(seeds, public, now=NOW)
        self.assertEqual((seeds, public), original)
        self.assertEqual(len(report["programmes"]), 251)
        self.assertEqual(report["summary"]["current_confirmed_deadlines"], 1)
        self.assertEqual(report["summary"]["remaining_programmes"], 250)
        self.assertEqual(sum(report["summary"]["reason_counts"].values()), 251)
        self.assertEqual(report["summary"]["reason_counts"]["robots_disallowed"], 1)
        self.assertFalse(report["summary"]["all_programmes_have_current_deadlines"])
        self.assertIn("Respect the restriction", report["programmes"][4]["next_action"])
        self.assertIn("University 250 (US)", text_report(report))

    def test_freshness_boundary_and_deadline_day_are_exact(self):
        seeds, public = catalogues()
        row = public["programmes"][0]
        verify(row)
        row.update(checked_at=(NOW - timedelta(days=14)).isoformat(),
                   deadline_iso="2026-11-24", evidence_excerpt="Deadline: 24 November 2026")
        self.assertTrue(audit_catalogues(seeds, public, now=NOW)[
            "programmes"
        ][0]["current_deadline_confirmed"])
        row["checked_at"] = (NOW - timedelta(days=14, seconds=1)).isoformat()
        self.assertIn("stale_check", audit_catalogues(seeds, public, now=NOW)[
            "programmes"
        ][0]["issues"])
        verify(row)
        row.update(deadline_iso="2026-11-23", evidence_excerpt="Deadline: 23 November 2026")
        self.assertIn("expired_deadline", audit_catalogues(seeds, public, now=NOW)[
            "programmes"
        ][0]["issues"])

    def test_malformed_or_unproven_claims_never_count_as_current(self):
        cases = [
            ({"deadline_iso": "2027-02-30"}, "invalid_deadline"),
            ({"deadline_iso": "20270115"}, "invalid_deadline"),
            ({"deadline_iso": "2030-01-15"}, "out_of_range_deadline"),
            ({"checked_at": "2026-11-25T12:00:00Z"}, "future_check"),
            ({"checked_at": "2026-11-24T11:00:00"}, "missing_check"),
            ({"evidence_excerpt": "Application deadline: January 15"}, "unsupported_excerpt"),
            ({"evidence_excerpt": "Application deadline: January 14, 2027"}, "unsupported_excerpt"),
            ({"evidence_url": "https://example.edu.evil.test/phd"}, "invalid_evidence_url"),
            ({"evidence_url": "http://economics.example.edu/phd/0"}, "invalid_evidence_url"),
            ({"investigated_urls": []}, "unrecorded_evidence_url"),
            ({"official_programme_url": "https://other.example.edu/phd"}, "source_mismatch"),
        ]
        for change, expected in cases:
            with self.subTest(change=change):
                seeds, public = catalogues()
                verify(public["programmes"][0])
                public["programmes"][0].update(change)
                report = audit_catalogues(seeds, public, now=NOW)
                self.assertIn(expected, report["programmes"][0]["issues"])
                self.assertEqual(report["summary"]["current_confirmed_deadlines"], 0)

    def test_unconfirmed_status_is_not_promoted_by_an_iso_value(self):
        seeds, public = catalogues()
        verify(public["programmes"][0])
        public["programmes"][0]["status"] = "no_explicit_deadline"
        report = audit_catalogues(seeds, public, now=NOW)
        self.assertEqual(report["summary"]["current_confirmed_deadlines"], 0)
        self.assertIn("unexpected_deadline", report["programmes"][0]["issues"])

    def test_supported_collector_layouts_are_preserved(self):
        cases = [
            ("2027-02-02", "Application deadline Feb. 2, 2027"),
            ("2026-12-15", "Dec. 15, 2026 — Application deadline for Fall 2027"),
            ("2027-01-08", "Economics * English History Philosophy Theology January 8, 2027"),
            ("2027-01-15", "Application Deadline: 15/01/2027 14:00 CET"),
        ]
        for deadline, excerpt in cases:
            with self.subTest(excerpt=excerpt):
                seeds, public = catalogues()
                verify(public["programmes"][0])
                public["programmes"][0].update(deadline_iso=deadline, evidence_excerpt=excerpt)
                self.assertEqual(audit_catalogues(seeds, public, now=NOW)[
                    "summary"
                ]["current_confirmed_deadlines"], 1)

    def test_missing_duplicate_and_unexpected_observations_are_visible(self):
        seeds, public = catalogues()
        verify(public["programmes"][0])
        public["programmes"].append(copy.deepcopy(public["programmes"][0]))
        del public["programmes"][1]
        report = audit_catalogues(seeds, public, now=NOW)
        self.assertEqual(len(report["programmes"]), 251)
        self.assertEqual(report["programmes"][0]["reason"], "duplicate_observation")
        self.assertEqual(report["programmes"][1]["reason"], "missing_observation")
        public["programmes"].append({"institution": "Unregistered", "country_code": "US"})
        report = audit_catalogues(seeds, public, now=NOW)
        self.assertIn("observations_outside_seed_inventory", report["metadata_issues"])

    def test_full_coverage_requires_all_251_valid_records_and_trusted_metadata(self):
        seeds, public = catalogues()
        for row in public["programmes"]:
            verify(row)
        self.assertTrue(audit_catalogues(seeds, public, now=NOW)[
            "summary"
        ]["all_programmes_have_current_deadlines"])
        public["source"]["deadline_values_reused"] = True
        report = audit_catalogues(seeds, public, now=NOW)
        self.assertFalse(report["summary"]["all_programmes_have_current_deadlines"])
        self.assertEqual(report["summary"]["current_confirmed_deadlines"], 0)

    def test_cli_is_dependency_free_read_only_and_fails_incomplete_target(self):
        seeds, public = catalogues()
        verify(public["programmes"][0])
        with tempfile.TemporaryDirectory() as directory:
            seed_file, catalogue = Path(directory) / "seeds.json", Path(directory) / "public.json"
            seed_file.write_text(json.dumps(seeds), encoding="utf-8")
            catalogue.write_text(json.dumps(public), encoding="utf-8")
            before = seed_file.read_bytes(), catalogue.read_bytes()
            args = ["--seeds", str(seed_file), "--catalogue", str(catalogue),
                    "--now", NOW.isoformat(), "--json", "--require-all-verified"]
            run = subprocess.run(
                [sys.executable, "-S", str(ROOT / "tools/audit_phd_admissions.py"), *args],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(run.returncode, 1, run.stderr)
            self.assertEqual(json.loads(run.stdout)["summary"]["current_confirmed_deadlines"], 1)
            self.assertEqual((seed_file.read_bytes(), catalogue.read_bytes()), before)
            for row in public["programmes"]:
                verify(row)
            catalogue.write_text(json.dumps(public), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)


if __name__ == "__main__":
    unittest.main()
