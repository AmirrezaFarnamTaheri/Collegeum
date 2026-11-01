"""Static release safeguards for the one-use, main-only remediation dispatcher."""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from textwrap import dedent

WORKFLOW = Path(
    ".github/workflows/one-time-remediation-dispatch-20261102.yml"
)


class TrustedReleaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_only_reviewed_main_push_can_enter_release(self) -> None:
        self.assertIn("branches: [main]", self.text)
        self.assertIn(
            "paths: [.github/workflows/one-time-remediation-dispatch-20261102.yml]",
            self.text,
        )
        self.assertIn("github.repository == 'AmirrezaFarnamTaheri/Collegeum'", self.text)
        self.assertIn("github.ref == 'refs/heads/main'", self.text)
        self.assertIn("startsWith(github.event.head_commit.message,", self.text)
        self.assertIn(
            "ops: relaunch verified Collegeum remediation acceptance 20261102",
            self.text,
        )
        self.assertNotIn("workflow_dispatch:", self.text)
        self.assertNotIn("schedule:", self.text)
        self.assertIn("contents: read", self.text)
        self.assertIn("actions: write", self.text)
        self.assertIn("persist-credentials: false", self.text)

    def test_dry_run_and_inspection_precede_any_production_dispatch(self) -> None:
        inspection = self.text.index("dispatch_and_wait telegram-worker.yml inspect")
        dry_run = self.text.index("dispatch_and_wait pipeline.yml run -f dry_run=true")
        deploy = self.text.index("dispatch_and_wait telegram-worker.yml deploy")
        live = self.text.index("dispatch_and_wait pipeline.yml run -f dry_run=false")
        self.assertLess(inspection, dry_run)
        self.assertLess(dry_run, deploy)
        self.assertLess(deploy, live)
        self.assertIn("-f activate_webhook=false", self.text)
        self.assertIn("trusted_head", self.text)
        self.assertIn("Non-data changes appeared on main", self.text)
        self.assertIn("last_run.source_errors == 0", self.text)
        self.assertIn("last_run.sources.partial == 0", self.text)

    def test_failed_ci_job_stops_release_even_if_workflow_is_queued(self) -> None:
        marker = "        run: |\n"
        script = dedent(self.text.split(marker, 1)[1])
        gate = script[script.index("wait_integrated_checks() {"):
                      script.index("\nwait_run() {")]
        stub = r'''
set -euo pipefail
repo=Owner/Repo
GITHUB_SHA=sha123
GITHUB_STEP_SUMMARY=/dev/null
trusted_head() { :; }
workflow_runs() {
  if [ "$1" = ci.yml ]; then
    printf '%s\n' '{"workflow_runs":[{"id":123,"status":"queued",'\
      '"head_sha":"sha123","head_branch":"main","event":"push",'\
      '"created_at":"2026-11-01T00:00:00Z"}]}'
  else
    printf '%s\n' '{"workflow_runs":[{"id":456,"status":"completed",'\
      '"conclusion":"success","head_sha":"sha123",'\
      '"head_branch":"main","event":"push",'\
      '"created_at":"2026-11-01T00:00:00Z"}]}'
  fi
}
gh() { printf '%s\n' '{"jobs":[{"name":"test (3.11)","conclusion":"failure"}]}'; }
fatal() { printf 'FAIL-CLOSED: %s\n' "$*"; exit 55; }
notice() { :; }
sleep() { printf 'UNSAFE-WAIT\n'; exit 77; }
'''
        child = subprocess.run(
            ["bash", "-c", stub + "\n" + gate + "\nwait_integrated_checks\n"],
            capture_output=True, text=True,
        )
        self.assertEqual(child.returncode, 55, child.stdout + child.stderr)
        self.assertIn("FAIL-CLOSED:", child.stdout)
        self.assertNotIn("UNSAFE-WAIT", child.stdout)

    def test_embedded_bash_script_parses(self) -> None:
        marker = "        run: |\n"
        self.assertEqual(self.text.count(marker), 1)
        script = dedent(self.text.split(marker, 1)[1])
        check = subprocess.run(
            ["bash", "-n"], input=script, capture_output=True, text=True,
            check=False,
        )
        self.assertEqual(check.returncode, 0, check.stderr)


if __name__ == "__main__":
    unittest.main()
