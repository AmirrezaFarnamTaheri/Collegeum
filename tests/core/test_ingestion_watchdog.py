"""Test the pipeline recovery gate without network or secrets (stdlib only)."""
from datetime import UTC, datetime, timedelta
from unittest import TestCase

from tools.ingestion_watchdog import evaluate

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)
HEALTH_TIME = datetime(2026, 10, 29, 5, 49, 56, tzinfo=UTC)


def snapshot(when=HEALTH_TIME):
    return {"generated_at": when.isoformat().replace("+00:00", "Z"),
            "last_run": {"run_id": "40824188992", "outcome": "partial"}}


def run(when=HEALTH_TIME - timedelta(minutes=15), *, status="completed",
        conclusion="success", branch="main"):
    return {"created_at": when.isoformat().replace("+00:00", "Z"),
            "status": status, "conclusion": conclusion, "head_branch": branch,
            "name": "predoc-pipeline"}


class WatchdogDecisionTests(TestCase):
    def test_stale_snapshot_with_only_previous_completed_run_requests_recovery(self):
        result = evaluate(snapshot(), [run()], now=NOW)
        self.assertTrue(result.dispatch)
        self.assertEqual(result.reason, "stale-without-newer-run")
        self.assertGreater(result.age_seconds, 8 * 3600)

    def test_recent_snapshot_does_not_trigger_recovery(self):
        result = evaluate(snapshot(NOW - timedelta(minutes=55)), [run()], now=NOW)
        self.assertFalse(result.dispatch)
        self.assertEqual(result.reason, "fresh")

    def test_exactly_eight_hours_is_not_stale(self):
        result = evaluate(snapshot(NOW - timedelta(hours=8)), [run()], now=NOW)
        self.assertFalse(result.dispatch)
        self.assertEqual(result.reason, "fresh")

    def test_newer_in_progress_run_blocks_duplicate(self):
        pending = run(NOW - timedelta(minutes=10), status="in_progress")
        result = evaluate(snapshot(), [pending, run()], now=NOW)
        self.assertFalse(result.dispatch)
        self.assertEqual(result.reason, "pipeline-already-running")

    def test_any_queued_run_even_older_blocks_duplicate(self):
        result = evaluate(snapshot(), [run(status="queued")], now=NOW)
        self.assertFalse(result.dispatch)
        self.assertEqual(result.reason, "pipeline-already-running")

    def test_newer_completed_failed_run_means_manual_investigation_not_retry(self):
        failed = run(NOW - timedelta(minutes=30), conclusion="failure")
        result = evaluate(snapshot(), [failed, run()], now=NOW)
        self.assertFalse(result.dispatch)
        self.assertEqual(result.reason, "newer-run-without-health-checkpoint")

    def test_newer_success_without_updated_health_is_persistence_problem_not_retry(self):
        result = evaluate(snapshot(), [run(NOW - timedelta(minutes=20)), run()], now=NOW)
        self.assertFalse(result.dispatch)
        self.assertEqual(result.reason, "newer-run-without-health-checkpoint")

    def test_missing_or_unparseable_health_fails_closed(self):
        for health in ({}, {"generated_at": "sometime"}, {"generated_at": "2026-10-29"}):
            with self.subTest(health=health):
                result = evaluate(health, [run()], now=NOW)
                self.assertFalse(result.dispatch)
                self.assertEqual(result.reason, "invalid-health-timestamp")

    def test_future_health_timestamp_fails_closed(self):
        result = evaluate(snapshot(NOW + timedelta(minutes=10)), [run()], now=NOW)
        self.assertFalse(result.dispatch)
        self.assertEqual(result.reason, "future-health-timestamp")

    def test_unexpected_run_fields_and_missing_history_fail_closed(self):
        malformed = (
            None,
            [],
            [None],
            [{"created_at": "bogus", "head_branch": "main", "status": "completed"}],
            [{
                "created_at": "2026-10-29T12:00:00Z",
                "head_branch": "main",
                "status": "unclear",
            }],
        )
        for runs in malformed:
            with self.subTest(runs=runs):
                result = evaluate(snapshot(), runs, now=NOW)
                self.assertFalse(result.dispatch)
                self.assertEqual(result.reason, "untrusted-run-history")

    def test_non_main_branch_history_is_ignored(self):
        result = evaluate(snapshot(), [run(NOW, branch="feature"), run()], now=NOW)
        self.assertTrue(result.dispatch)

    def test_valid_offset_timestamp_is_normalized_to_utc(self):
        health = {"generated_at": "2026-10-29T07:49:56+02:00"}
        result = evaluate(health, [run()], now=NOW)
        self.assertTrue(result.dispatch)

    def test_stale_health_with_latest_skipped_or_cancelled_run_does_not_repeat(self):
        for conclusion in ("skipped", "cancelled", "timed_out"):
            with self.subTest(conclusion=conclusion):
                last_run = run(NOW - timedelta(hours=1), conclusion=conclusion)
                result = evaluate(snapshot(), [last_run], now=NOW)
                self.assertFalse(result.dispatch)
                self.assertEqual(result.reason, "newer-run-without-health-checkpoint")


class WatchdogCliTests(TestCase):
    def _run_cli(self, *, age_days=1, runs=None, api_error=None, dispatch=True):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import Mock, patch

        from tools import ingestion_watchdog as watchdog

        generated = datetime.now(UTC) - timedelta(days=age_days)
        health = snapshot(generated)
        historic = run(generated - timedelta(minutes=10))
        if runs is None:
            runs = [historic]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "health.json"
            path.write_text(json.dumps(health), encoding="utf-8")
            output = {"workflow_runs": runs}
            request = Mock(side_effect=api_error) if api_error else Mock(side_effect=[output, None])
            env = {"GH_TOKEN": "not-a-real-token", "GITHUB_REPOSITORY": "Owner/Repo"}
            args = ["--health", str(path)] + (["--dispatch"] if dispatch else [])
            with patch.dict("os.environ", env), patch.object(watchdog, "_request", request):
                status = watchdog.main(args)
            return status, request

    def test_cli_requests_one_new_production_dispatch_when_safe(self):
        status, request = self._run_cli()
        self.assertEqual(status, 0)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(
            request.call_args_list[0].args[0],
            "https://api.github.com/repos/Owner/Repo/actions/workflows/"
            "pipeline.yml/runs?branch=main&per_page=50",
        )
        self.assertEqual(
            request.call_args_list[1].args[0],
            "https://api.github.com/repos/Owner/Repo/actions/workflows/"
            "pipeline.yml/dispatches",
        )
        self.assertEqual(request.call_args_list[1].kwargs["payload"],
                         {"ref": "main", "inputs": {"dry_run": "false"}})

    def test_cli_check_only_never_dispatches(self):
        status, request = self._run_cli(dispatch=False)
        self.assertEqual(status, 0)
        self.assertEqual(request.call_count, 1)

    def test_cli_fresh_snapshot_never_dispatches(self):
        status, request = self._run_cli(age_days=0)
        self.assertEqual(status, 0)
        self.assertEqual(request.call_count, 1)

    def test_cli_newer_run_never_dispatches(self):
        status, request = self._run_cli(runs=[run(datetime.now(UTC) - timedelta(minutes=10))])
        self.assertEqual(status, 0)
        self.assertEqual(request.call_count, 1)

    def test_cli_api_error_fails_closed_without_dispatch(self):
        api_error = RuntimeError("GitHub Actions API connection failed")
        status, request = self._run_cli(api_error=api_error)
        self.assertEqual(status, 1)
        self.assertEqual(request.call_count, 1)


class WatchdogWorkflowSafetyTests(TestCase):
    def test_privileged_trigger_is_main_only_and_uses_read_only_checkout(self):
        from pathlib import Path
        workflow = Path(
            ".github/workflows/ingestion-freshness-recovery.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('actions: write', workflow)
        self.assertIn('contents: read', workflow)
        self.assertIn('branches: [main]', workflow)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", workflow)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", workflow)
        self.assertIn(
            "github.event.workflow_run.head_repository.full_name == github.repository",
            workflow,
        )
        self.assertIn('persist-credentials: false', workflow)
        self.assertIn('ref: main', workflow)
        self.assertNotIn('on:\n  schedule:', workflow)
