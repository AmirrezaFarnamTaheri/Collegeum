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
