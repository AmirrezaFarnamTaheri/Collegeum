"""Freshness is not proof of healthy ingestion or successful publication (#52)."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tools import ingestion_watchdog as watchdog


HEALTH = {
    "generated_at": "2026-11-21T15:50:06Z",
    "last_run": {
        "run_id": "44920463596", "outcome": "partial", "published": 0,
    },
    "source_summary": {
        "total": 75, "successful": 59, "empty": 10,
        "failed": 3, "partial": 1, "skipped": 2,
    },
}


class HealthOutcomeSeparationTests(TestCase):
    def test_fresh_partial_ingestion_is_never_printed_as_healthy(self) -> None:
        now = datetime(2026, 11, 21, 16, 0, tzinfo=UTC)
        recent = watchdog.Decision(False, "fresh", age_seconds=594)
        data = watchdog.health_evidence(HEALTH)
        self.assertTrue(data.counts_verified)
        self.assertEqual(data.outcome, "partial")
        self.assertEqual(data.run_id, "44920463596")
        self.assertEqual(data.published, 0)
        self.assertEqual(data.sources_failed, 3)
        self.assertEqual(data.sources_partial, 1)
        self.assertEqual(
            watchdog.evaluate(HEALTH, [], now=now).reason, "fresh",
        )
        buffer = StringIO()
        with TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"
            with patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(summary)}):
                with redirect_stdout(buffer):
                    watchdog._summary(recent, "none", health=HEALTH)
            text = summary.read_text(encoding="utf-8")
        result = buffer.getvalue()
        self.assertIn("Ingestion watchdog: fresh", result)
        self.assertIn("Application snapshot: partial", result)
        self.assertIn("3 failed, 1 partial", result)
        self.assertIn("published in run: 0", result)
        self.assertIn("::warning title=Degraded ingestion snapshot::", result)
        self.assertIn("Application outcome: **partial**", text)
        self.assertIn("Publication attempts in snapshot run: **0**", text)
        self.assertIn("Source health: **59 successful", text)

    def test_untrusted_source_counts_are_unverified_not_coerced(self) -> None:
        forged = {
            **HEALTH,
            "last_run": {
                "run_id": "123\n::warning title=TOKEN::", "outcome": "success\nSECRET",
                "published": -1,
            },
            "source_summary": {
                "total": 2, "successful": True, "empty": 0,
                "failed": "2", "partial": 0, "skipped": 0,
            },
        }
        data = watchdog.health_evidence(forged)
        self.assertFalse(data.counts_verified)
        self.assertEqual(data.outcome, "unverified")
        self.assertEqual(data.run_id, "unverified")
        self.assertIsNone(data.published)
        buffer = StringIO()
        with redirect_stdout(buffer):
            watchdog._summary(
                watchdog.Decision(False, "fresh", age_seconds=5),
                "none", health=forged,
            )
        self.assertNotIn("SECRET", buffer.getvalue())
        self.assertNotIn("TOKEN", buffer.getvalue())
        self.assertIn("Application snapshot: unverified", buffer.getvalue())
        self.assertIn("source counts unverified", buffer.getvalue())

    def test_inconsistent_totals_and_missing_public_health_do_not_claim_success(self) -> None:
        invalid = {
            **HEALTH,
            "source_summary": {
                "total": 75, "successful": 59, "empty": 10,
                "failed": 3, "partial": 1, "skipped": 1,
            },
        }
        self.assertFalse(watchdog.health_evidence(invalid).counts_verified)
        self.assertEqual(watchdog.health_evidence({}).outcome, "unverified")
        self.assertFalse(watchdog.health_evidence({}).counts_verified)
