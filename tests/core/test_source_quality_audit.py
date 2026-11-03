"""Offline evidence contract for public Collegeum quality audits (stdlib)."""
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tools.audit_source_quality import audit, main

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)


def fixture(root: Path, *, career_rows=None, career_sources=None, life=None,
            general=None, dashboard=None):
    (root / "data").mkdir(parents=True)
    (root / "docs/data").mkdir(parents=True)
    rows = career_rows if career_rows is not None else [
        {"key": "career:1", "url": "https://example.org/jobs/1", "category": "life_sciences_phd",
         "funding_status": "unverified", "first_seen_at": "2026-11-01T10:00:00Z",
         "last_seen_at": "2026-11-01T10:00:00Z"},
    ]
    (root / "data/career_jobs.ndjson").write_text(
        "".join(json.dumps(x) + "\n" for x in rows), encoding="utf-8")
    career = {"checked_at": "2026-11-03T09:00:00Z", "sources": career_sources or {
        "jobinja": {"status": "blocked_robots", "fetched": 0,
                    "next_robots_check_at": "2026-11-09T18:16:06Z"},
        "irantalent": {"status": "empty", "fetched": 1},
    }}
    (root / "data/career_health.json").write_text(json.dumps(career), encoding="utf-8")
    life = life or {"checked_at": "2026-11-03T09:00:00Z",
                    "catalogue": {"total": 40, "enabled": 2, "disabled": 38},
                    "checked_this_run": 1,
                    "summary_this_run": {"discovered": 1, "partial": 0},
                    "sources": {
                        "life_a": {
                            "status": "discovered", "last_checked_at": "2026-11-03T09:00:00Z"
                        },
                        "life_b": {"status": "partial", "detail_failures": 2,
                                   "last_checked_at": "2026-11-02T05:00:00Z"},
                    }}
    (root / "data/life_sources_health.json").write_text(json.dumps(life), encoding="utf-8")
    general = general or {"generated_at": "2026-10-01T09:00:00Z",
                          "last_run": {"run_id": "12345", "outcome": "ok", "source_errors": 0,
                                       "sources": {"total": 3, "successful": 2,
                                                   "empty": 0, "failed": 0,
                                                   "partial": 0, "skipped": 1}},
                          "source_summary": {"total": 3, "successful": 2,
                                             "empty": 0, "failed": 0,
                                             "partial": 0, "skipped": 1}}
    (root / "docs/data/health.json").write_text(json.dumps(general), encoding="utf-8")
    dashboard = dashboard or {"listings": [
        {"id": 7, "kind": "predoc", "apply_url": "https://example.edu/position/7",
         "deadline": None, "visa": "unknown"}]}
    (root / "docs/data/listings.json").write_text(json.dumps(dashboard), encoding="utf-8")


class SourceQualityTests(unittest.TestCase):
    def test_unknown_and_provider_active_are_not_independently_verified_open(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root, career_rows=[
                {"key": "career:1", "url": "https://example.org/jobs/1",
                 "category": "life_sciences_phd", "funding_status": "unverified",
                 "last_seen_at": "2026-11-01T00:00:00Z"},
                {"key": "career:2", "url": "https://example.org/jobs/2", "availability": "active",
                 "category": "research_analyst", "last_seen_at": "2026-10-20T00:00:00Z",
                 "deadline": "2026-10-31"},
            ])
            report = audit(root, now=NOW)
            career = report["career"]
            self.assertEqual(career["availability"], {
                "unknown": 1, "provider_marked_active": 1, "closed": 0})
            self.assertEqual(career["verified_open_count"], 0)
            self.assertEqual(career["funding_unverified"], 2)
            self.assertEqual(career["last_seen_older_than_7d"], 1)
            self.assertEqual(career["deadline_elapsed_not_proof_closed"], 1)
            self.assertEqual(report["integrity_findings"], [])

    def test_historical_life_partials_are_not_counted_as_this_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            report = audit(root, now=NOW)
            life = report["life_sciences"]
            self.assertEqual(life["checked_this_run"], 1)
            self.assertEqual(life["observation_statuses"]["partial"], 1)
            self.assertEqual(life["summary_this_run"]["partial"], 0)
            self.assertEqual(life["catalogue"]["enabled"], 2)
            self.assertEqual(life["historical_partial_observations"], 1)
            self.assertIn("life:historic-partial-observations", report["operational_observations"])

    def test_blocked_provider_is_never_marked_empty_or_retried_early(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            report = audit(root, now=NOW)
            self.assertEqual(report["career_sources"]["statuses"],
                             {"blocked_robots": 1, "empty": 1})
            self.assertEqual(report["career_sources"]["blocked_without_fetch"], 1)
            self.assertEqual(report["career_sources"]["next_policy_rechecks_known"], 1)
            self.assertIn("career:blocked-by-site-policy", report["operational_observations"])
            self.assertEqual(report["integrity_findings"], [])

    def test_duplicate_keys_or_invalid_urls_fail_without_exposing_job_urls(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root, career_rows=[
                {"key": "career:repeat", "url": "https://example.org/jobs/a",
                 "category": "research_analyst"},
                {"key": "career:repeat", "url": "https://example.org/jobs/b",
                 "category": "research_analyst"},
                {"key": "career:third", "url": "https://user:password@example.org/secret",
                 "category": "research_analyst"},
            ])
            report = audit(root, now=NOW)
            self.assertEqual(report["career"]["duplicate_key_rows"], 1)
            self.assertEqual(report["career"]["unsafe_application_url_rows"], 1)
            self.assertIn("career:duplicate-keys", report["integrity_findings"])
            self.assertIn("career:unsafe-application-urls", report["integrity_findings"])
            self.assertNotIn("secret", json.dumps(report))
            self.assertNotIn("password", json.dumps(report))

    def test_source_counts_mismatch_is_integrity_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            general = {"generated_at": "2026-11-03T09:00:00Z",
                       "last_run": {"run_id": "123", "outcome": "ok",
                                    "sources": {"total": 5, "successful": 2, "empty": 0,
                                                "failed": 0, "partial": 0, "skipped": 1}},
                       "source_summary": {"total": 5, "successful": 2, "empty": 0,
                                          "failed": 0, "partial": 0, "skipped": 1}}
            fixture(root, general=general)
            report = audit(root, now=NOW)
            self.assertIn("general:source-count-mismatch", report["integrity_findings"])

    def test_malformed_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            (root / "data/life_sources_health.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                audit(root, now=NOW)

    def test_cli_strict_sets_failure_exit_only_on_structural_defects(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            dest = root / "build/report.json"
            self.assertEqual(main(["--root", str(root), "--output", str(dest), "--strict"]), 0)
            self.assertTrue(dest.exists())
            self.assertEqual(json.loads(dest.read_text())["integrity_findings"], [])
            broken = root / "data/career_jobs.ndjson"
            broken.write_text(broken.read_text() * 2, encoding="utf-8")
            self.assertEqual(main(["--root", str(root), "--output", str(dest), "--strict"]), 2)

    def test_readonly_workflow_follows_production_and_uses_trusted_main(self):
        workflow = (Path(__file__).resolve().parents[2] /
                    ".github/workflows/source-quality-audit.yml").read_text(encoding="utf-8")
        for expected in ('workflows: ["predoc-pipeline"]', "types: [completed]",
                         "github.event.workflow_run.head_branch == 'main'",
                         "github.event.workflow_run.head_repository.full_name == github.repository",
                         "contents: read", "persist-credentials: false",
                         "ref: main", "--strict", "actions/upload-artifact@v7"):
            self.assertIn(expected, workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("actions: write", workflow)
        self.assertNotIn("git push", workflow)


if __name__ == "__main__":
    unittest.main()
