"""Regression tests for production automation invariants (stdlib only).

CI tests cannot exercise live tokens or GitHub Pages, but they can refuse to
accept workflow edits that remove the critical safety/locking contracts.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def workflow(filename: str) -> str:
    return (WORKFLOWS / filename).read_text(encoding="utf-8")


class WorkflowContractTests(unittest.TestCase):
    def test_ci_is_unprivileged_and_uses_checked_lock(self):
        content = workflow("ci.yml")
        self.assertIn("contents: read", content)
        self.assertIn("workflow_dispatch:", content)
        self.assertIn("uv lock --check", content)
        self.assertIn("uv sync --locked", content)
        self.assertIn("uv build --out-dir build/release", content)
        self.assertIn("tools/verify_release.py", content)

    def test_live_workflows_only_run_on_main(self):
        for name in ("pipeline.yml", "telegram.yml"):
            with self.subTest(name=name):
                content = workflow(name)
                self.assertIn("if: github.ref == 'refs/heads/main'", content)
                self.assertIn("uv sync --locked", content)
                self.assertIn("queue: max", content)
        pipeline = workflow("pipeline.yml")
        self.assertIn("timeout-minutes: 120", pipeline)
        self.assertIn("github.event.inputs.dry_run != 'true'", pipeline)
        self.assertIn(
            "vars.ENABLE_TELEGRAM_SYNC != 'false'", workflow("telegram.yml"),
        )

    def test_private_telegram_requires_credentials_or_explicit_disable(self):
        content = workflow("telegram.yml")
        self.assertIn("vars.ENABLE_TELEGRAM_SYNC != 'false'", content)
        guard = content.index("name: Require live private Telegram credentials")
        private_checkout = content.index("name: Checkout authoritative private state")
        sync = content.index("name: Process private commands")
        self.assertLess(guard, private_checkout)
        self.assertLess(private_checkout, sync)
        self.assertIn('if [ -z "$TELEGRAM_BOT_TOKEN" ]', content)
        self.assertIn('if [ -z "$FEEDBACK_ENCRYPTION_KEY" ]', content)
        self.assertIn("::error::FEEDBACK_ENCRYPTION_KEY was not injected", content)
        self.assertIn("::error::TELEGRAM_BOT_TOKEN is missing", content)
        self.assertNotIn('echo "private_enabled=false"', content)
        self.assertNotIn("bot disabled.", content)
        self.assertIn('if [ "$SYNC_OUTCOME" != "success" ]', content)

    def test_failed_sync_keeps_recovery_and_failing_status(self):
        telegram = workflow("telegram.yml")
        self.assertIn("continue-on-error: true", telegram)
        self.assertIn("always() && steps.sync.outcome != 'skipped'", telegram)
        self.assertIn('if [ "$SYNC_OUTCOME" != "success" ]', telegram)
        pipeline = workflow("pipeline.yml")
        self.assertIn('if [ "$PIPELINE_OUTCOME" != "success" ]', pipeline)
        self.assertIn("always() && steps.pipeline.outcome != 'skipped'", pipeline)

    def test_private_sends_require_a_persisted_outbox(self):
        workflow_text = workflow("telegram.yml")
        stages = (
            "id: sync", "subscriber-plan", "id: checkpoint",
            'git commit -m "chore: checkpoint Telegram inbox',
            "id: delivery", "subscriber-send",
            "id: acknowledgement", 'git commit -m "chore: record private delivery',
        )
        positions = [workflow_text.index(stage) for stage in stages]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("steps.checkpoint.outcome == 'success'", workflow_text)
        self.assertIn("steps.sync.outputs.private_enabled == 'true'", workflow_text)
        self.assertIn("steps.delivery.outcome != 'skipped'", workflow_text)
        self.assertIn('if [ "$SYNC_OUTCOME" != "success" ]', workflow_text)

    def test_cadence_and_source_rotation_share_four_hour_slots(self):
        pipeline = workflow("pipeline.yml")
        self.assertIn('cron: "7 */4 * * *"', pipeline)
        self.assertIn("SOURCE_ROTATION_ENABLED", pipeline)
        self.assertIn("data/career_jobs.ndjson", pipeline)
        self.assertIn("data/career_health.json", pipeline)
        self.assertIn("data/source_rotation.json", pipeline)

    def test_pages_never_deploys_failed_or_cross_branch_run(self):
        content = workflow("pages.yml")
        for guard in (
            "vars.ENABLE_PAGES == 'true'",
            "github.ref == 'refs/heads/main'",
            "github.event.workflow_run.conclusion == 'success'",
            "github.event.workflow_run.head_branch == 'main'",
            "github.event.workflow_run.head_repository.full_name == github.repository",
        ):
            self.assertIn(guard, content)
        self.assertIn("actions/upload-pages-artifact@v5", content)
        self.assertIn("actions/configure-pages@v6", content)
        self.assertIn("actions/deploy-pages@v5", content)

    def test_pages_excludes_operational_guides_from_artifact(self):
        content = workflow("pages.yml")
        self.assertIn("path: build/pages", content)
        self.assertIn("Stage public dashboard assets", content)
        self.assertIn("docs/data", content)
        self.assertNotIn("path: docs\n", content)
        self.assertNotIn("cp -r docs", content)

    def test_distribution_is_generated_without_mutating_branches(self):
        content = workflow("refresh-release.yml")
        self.assertIn("contents: read", content)
        self.assertIn("tools/build_single_file.py", content)
        self.assertIn("tools/verify_single_file.py", content)
        self.assertIn("actions/upload-artifact@v7", content)
        self.assertNotIn("git push", content)
        self.assertNotIn("contents: write", content)
        release = workflow("publish-distribution.yml")
        self.assertIn("release:", release)
        self.assertIn("gh release upload", release)
        ci = workflow("ci.yml")
        self.assertIn("python3 tools/build_single_file.py", ci)

    def test_private_state_backend_rejects_public_state_writes(self):
        for workflow_name in ("telegram.yml", "pipeline.yml"):
            with self.subTest(workflow=workflow_name):
                content = workflow(workflow_name)
                self.assertIn("PRIVATE_STATE_REPO", content)
                self.assertIn("private_state.py checkpoint", content)
                self.assertIn("private_state.py restore", content)
                self.assertIn("Refusing to store subscriber state in a public", content)


    def test_missing_private_key_does_not_disable_public_channel(self):
        pipeline_code = (ROOT / "src/predoc_pipeline/pipeline.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"telegram_private_sync_skipped"', pipeline_code)
        self.assertIn('public_channel="unaffected"', pipeline_code)
        self.assertIn(
            'settings.telegram_feedback_buttons and settings.feedback_encryption_key',
            pipeline_code,
        )
        telegram = workflow("telegram.yml")
        self.assertIn("Public channel announcements use TELEGRAM_BOT_TOKEN", telegram)
        self.assertIn("FEEDBACK_ENCRYPTION_KEY was not injected", telegram)


if __name__ == "__main__":
    unittest.main()
