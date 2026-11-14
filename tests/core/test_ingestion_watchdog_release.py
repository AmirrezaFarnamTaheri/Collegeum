"""A successful publisher release must not be masked by fresh old data."""
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from tools import ingestion_watchdog as watchdog

NOW = datetime(2026, 11, 14, 20, 0, tzinfo=UTC)
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
RUN_CREATED = "2026-11-14T17:54:57Z"
CI_CREATED = "2026-11-14T19:43:46Z"


def old_pipeline_run(*, created_at=RUN_CREATED, status="completed", head_sha=OLD_SHA):
    return {
        "name": "predoc-pipeline", "head_branch": "main",
        "created_at": created_at, "status": status,
        "conclusion": "success", "head_sha": head_sha,
    }


def change(files=("src/predoc_pipeline/pipeline.py",)):
    return {
        "status": "ahead", "base_commit": {"sha": OLD_SHA},
        "files": [{"filename": p, "status": "modified"} for p in files],
    }


class PublisherRevisionDecisionTests(TestCase):
    def test_fresh_health_does_not_mask_new_publisher_not_yet_run(self):
        baseline = watchdog.evaluate(
            {"generated_at": "2026-11-14T18:03:22Z"},
            [old_pipeline_run()], now=NOW,
        )
        self.assertEqual(baseline.reason, "fresh")
        result = watchdog.evaluate_publisher_revision(
            [old_pipeline_run()], change(), now=NOW,
            trigger_created_at=CI_CREATED, main_sha=NEW_SHA,
        )
        self.assertTrue(result.dispatch)
        self.assertEqual(result.reason, "publisher-revision-not-ingested")

    def test_existing_or_inflight_newer_ingestion_never_replays(self):
        for later in (
            old_pipeline_run(created_at="2026-11-14T19:44:00Z"),
            old_pipeline_run(status="in_progress"),
            old_pipeline_run(head_sha=NEW_SHA),
        ):
            with self.subTest(later=later):
                result = watchdog.evaluate_publisher_revision(
                    [later, old_pipeline_run()], change(), now=NOW,
                    trigger_created_at=CI_CREATED, main_sha=NEW_SHA,
                )
                self.assertFalse(result.dispatch)

    def test_unrelated_code_and_unsafe_compare_responses_do_not_dispatch(self):
        for diff in (
            change(("docs/README.md",)), {},
            {"status": "diverged", "base_commit": {"sha": OLD_SHA},
             "files": [{"filename": "src/predoc_pipeline/pipeline.py"}]},
            {"status": "ahead", "base_commit": {"sha": "c" * 40},
             "files": [{"filename": "src/predoc_pipeline/pipeline.py"}]},
            {"status": "ahead", "base_commit": {"sha": OLD_SHA}, "files": None},
        ):
            with self.subTest(diff=diff):
                result = watchdog.evaluate_publisher_revision(
                    [old_pipeline_run()], diff, now=NOW,
                    trigger_created_at=CI_CREATED, main_sha=NEW_SHA,
                )
                self.assertFalse(result.dispatch)

    def test_unknown_history_and_invalid_trigger_metadata_fail_closed(self):
        for runs, trigger, sha in (
            ([], CI_CREATED, NEW_SHA),
            ([old_pipeline_run(head_sha="not-a-sha")], CI_CREATED, NEW_SHA),
            ([old_pipeline_run()], "not-a-timestamp", NEW_SHA),
            ([old_pipeline_run()], CI_CREATED, "invalid"),
        ):
            with self.subTest(runs=runs, trigger=trigger):
                result = watchdog.evaluate_publisher_revision(
                    runs, change(), now=NOW,
                    trigger_created_at=trigger, main_sha=sha,
                )
                self.assertFalse(result.dispatch)


class PublisherRevisionCliTests(TestCase):
    def test_fresh_health_authorized_ci_revision_dispatches_once(self):
        with tempfile.TemporaryDirectory() as directory:
            health_path = Path(directory) / "health.json"
            health_path.write_text(
                json.dumps({"generated_at": (datetime.now(UTC) - timedelta(hours=1))
                            .isoformat()}), encoding="utf-8",
            )
            # Triggered after the old pipeline but before this CI run; use
            # an actual recent timestamp so metadata is never future-dated.
            ci_created = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()
            older_run = old_pipeline_run(
                created_at=(datetime.now(UTC) - timedelta(hours=3)).isoformat(),
            )
            requests = Mock(side_effect=[
                {"workflow_runs": [older_run]},
                change(),
                None,
            ])
            with patch.dict("os.environ", {
                "GH_TOKEN": "test", "GITHUB_REPOSITORY": "Owner/Repo",
                "RELEASE_CHECK": "true", "GITHUB_SHA": NEW_SHA,
                "CI_HEAD_SHA": NEW_SHA,
                "CI_RUN_CREATED_AT": ci_created,
            }), patch.object(watchdog, "_request", requests):
                result = watchdog.main(["--health", str(health_path), "--dispatch"])
            self.assertEqual(result, 0)
            self.assertEqual(requests.call_count, 3)
            self.assertIn("/compare/" + OLD_SHA + "..." + NEW_SHA,
                          requests.call_args_list[1].args[0])
            self.assertEqual(
                requests.call_args_list[2].kwargs["payload"],
                {"ref": "main", "inputs": {"dry_run": "false"}},
            )

    def test_trigger_provenance_only_allows_trusted_main_ci(self):
        workflow = Path(
            ".github/workflows/ingestion-freshness-recovery.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository",
                      workflow)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", workflow)
        self.assertIn("github.event.workflow_run.event == 'push'", workflow)
        self.assertIn("RELEASE_CHECK:", workflow)
        self.assertIn("CI_RUN_CREATED_AT:", workflow)
        self.assertIn("CI_HEAD_SHA:", workflow)
