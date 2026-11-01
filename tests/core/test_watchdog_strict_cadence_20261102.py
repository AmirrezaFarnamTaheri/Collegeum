"""Strict ingestion-cadence acceptance: visible failure without extra dispatches."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tools import ingestion_watchdog as watchdog


def _run(created: datetime) -> dict[str, str]:
    return {
        "created_at": created.isoformat(),
        "status": "completed",
        "head_branch": "main",
        "event": "schedule",
        "name": "predoc-pipeline",
    }


class StrictCadenceTests(TestCase):
    def _check(self, runs: list[dict[str, str]]) -> tuple[int, int]:
        now = datetime.now(UTC)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "health.json"
            path.write_text(
                json.dumps({"generated_at": (now - timedelta(minutes=5)).isoformat()}),
                encoding="utf-8",
            )
            with (
                patch.dict("os.environ", {
                    "GH_TOKEN": "offline-test-token",
                    "GITHUB_REPOSITORY": "Owner/Repo",
                    "GITHUB_STEP_SUMMARY": "",
                }),
                patch.object(
                    watchdog, "_request", return_value={"workflow_runs": runs}
                ) as request,
            ):
                status = watchdog.main(["--health", str(path), "--strict-cadence"])
        return status, request.call_count

    def test_verified_missing_mature_slots_fail_even_with_fresh_health(self) -> None:
        status, calls = self._check([_run(datetime.now(UTC) - timedelta(hours=26))])
        self.assertEqual(status, 2)
        self.assertEqual(calls, 1)  # No duplicate publication/dispatch.

    def test_incomplete_run_history_does_not_invent_missing_slots(self) -> None:
        status, calls = self._check([_run(datetime.now(UTC) - timedelta(minutes=30))])
        self.assertEqual(status, 0)
        self.assertEqual(calls, 1)

    def test_recovery_workflow_activates_strict_cadence_for_both_modes(self) -> None:
        workflow = Path(
            ".github/workflows/ingestion-freshness-recovery.yml"
        ).read_text(encoding="utf-8")
        self.assertEqual(workflow.count("--strict-cadence"), 2)
