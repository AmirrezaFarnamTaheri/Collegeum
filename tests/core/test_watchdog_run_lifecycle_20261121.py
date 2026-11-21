"""Read-only scheduled-workflow lifecycle evidence for ingestion cadence (#52)."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import UTC, datetime
from io import StringIO
from unittest import TestCase

from tools.ingestion_watchdog import Decision, _summary, audit_cadence

NOW = datetime(2026, 11, 21, 13, 30, tzinfo=UTC)


def scheduled(
    created: str, *, status: str = "completed",
    conclusion: str | None = "success", event: str = "schedule",
    started: str | None = None, attempt: int = 1,
) -> dict[str, object]:
    return {
        "name": "predoc-pipeline",
        "head_branch": "main",
        "event": event,
        "created_at": created,
        "status": status,
        "conclusion": conclusion,
        "run_attempt": attempt,
        **({"run_started_at": started} if started is not None else {}),
    }


class ScheduledRunLifecycleTests(TestCase):
    def test_counts_failures_cancellations_pending_and_reruns_separately(self) -> None:
        rows = [
            scheduled("2026-11-20T12:00:00Z"),  # Proves history predates window.
            scheduled(
                "2026-11-21T04:09:00Z",
                started="2026-11-21T04:12:00Z",
                conclusion="cancelled",
            ),
            scheduled(
                "2026-11-21T08:20:00Z",
                status="queued", conclusion=None,
            ),
            scheduled(
                "2026-11-21T12:27:00Z",
                started="2026-11-21T12:42:00Z",
                conclusion="failure", attempt=2,
            ),
            scheduled(
                "2026-11-21T10:00:00Z",
                started="2026-11-21T10:01:00Z",
                event="workflow_dispatch", conclusion="success",
            ),
        ]
        result = audit_cadence(rows, now=NOW)
        self.assertTrue(result.verified)
        self.assertEqual(result.scheduled_completed_success, 0)
        self.assertEqual(result.scheduled_completed_failure, 1)
        self.assertEqual(result.scheduled_cancelled, 1)
        self.assertEqual(result.scheduled_active, 1)
        self.assertEqual(result.scheduled_reruns, 1)
        # "Run started" is an Actions workflow timestamp, not runner checkout.
        self.assertEqual(result.max_workflow_start_lag_seconds, 15 * 60)
        self.assertEqual(result.workflow_start_lag_unverified, 1)

    def test_invalid_or_missing_workflow_start_is_unknown_not_zero(self) -> None:
        rows = [
            scheduled("2026-11-20T12:00:00Z"),
            scheduled(
                "2026-11-21T12:27:00Z",
                started="2026-11-21T12:20:00Z",
            ),
        ]
        result = audit_cadence(rows, now=NOW)
        self.assertTrue(result.verified)
        self.assertIsNone(result.max_workflow_start_lag_seconds)
        self.assertEqual(result.workflow_start_lag_unverified, 1)

    def test_summary_distinguishes_workflow_lifecycle_from_publication(self) -> None:
        rows = [
            scheduled("2026-11-20T12:00:00Z"),
            scheduled(
                "2026-11-21T12:27:00Z",
                started="2026-11-21T12:42:00Z",
                conclusion="failure",
            ),
        ]
        result = audit_cadence(rows, now=NOW)
        output = StringIO()
        with redirect_stdout(output):
            _summary(Decision(False, "fresh", age_seconds=60), "none", cadence=result)
        message = output.getvalue()
        self.assertIn("completed failed: 1", message)
        self.assertIn("workflow start lag", message)
        self.assertIn("not runner checkout latency", message)
        self.assertIn("action: none", message)
