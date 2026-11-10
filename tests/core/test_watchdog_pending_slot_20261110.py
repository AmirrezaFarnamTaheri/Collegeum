"""Read-only creation-time audit for not-yet-mature late cron windows."""
from datetime import UTC, datetime
from unittest import TestCase

from tools.ingestion_watchdog import audit_cadence


def event(at: str, *, kind: str = "schedule", name: str | None = "predoc-pipeline") -> dict:
    record = {
        "created_at": at,
        "event": kind,
        "head_branch": "main",
        "status": "completed",
    }
    if name is not None:
        record["name"] = name
    return record


# The old record establishes that API history covers the first inspected tick.
HISTORY = event("2026-11-08T20:23:05Z")
PREVIOUS = event("2026-11-10T02:39:03Z")


class PendingLateSlotTests(TestCase):
    def test_unobserved_30_minute_overdue_slot_is_late_but_not_mature(self):
        now = datetime(2026, 11, 10, 6, 42, 16, tzinfo=UTC)
        manual = event("2026-11-10T05:30:00Z", kind="workflow_dispatch")
        audit = audit_cadence([manual, PREVIOUS, HISTORY], now=now)
        self.assertTrue(audit.verified)
        self.assertEqual(audit.late_pending, 1)
        self.assertEqual(audit.late_pending_ticks, ("2026-11-10T04:07:00Z",))
        self.assertNotIn("2026-11-10T04:07:00Z", audit.missing_ticks)
        self.assertEqual(audit.unsettled, 1)

    def test_exactly_30_minutes_is_not_late_but_one_second_later_is(self):
        exactly = audit_cadence(
            [PREVIOUS, HISTORY], now=datetime(2026, 11, 10, 4, 37, tzinfo=UTC)
        )
        overdue = audit_cadence(
            [PREVIOUS, HISTORY], now=datetime(2026, 11, 10, 4, 37, 1, tzinfo=UTC)
        )
        self.assertEqual(exactly.late_pending, 0)
        self.assertEqual(overdue.late_pending, 1)

    def test_four_hour_maturity_replaces_pending_lateness_with_missing(self):
        audit = audit_cadence(
            [PREVIOUS, HISTORY], now=datetime(2026, 11, 10, 8, 7, tzinfo=UTC)
        )
        self.assertIn("2026-11-10T04:07:00Z", audit.missing_ticks)
        self.assertNotIn("2026-11-10T04:07:00Z", audit.late_pending_ticks)
        self.assertEqual(audit.late_pending, 0)

    def test_schedule_with_unverified_workflow_name_does_not_fill_slot(self):
        nameless = event("2026-11-10T04:50:00Z", name=None)
        audit = audit_cadence(
            [nameless, PREVIOUS, HISTORY],
            now=datetime(2026, 11, 10, 6, 42, 16, tzinfo=UTC),
        )
        self.assertEqual(audit.late_pending_ticks, ("2026-11-10T04:07:00Z",))
