"""Trusted failed scheduled syncs must still provide freshness recovery triggers."""
from __future__ import annotations

import re
from pathlib import Path


def test_failed_scheduled_sync_can_invoke_guarded_freshness_recovery():
    workflow = Path(".github/workflows/ingestion-freshness-recovery.yml").read_text(
        encoding="utf-8"
    )
    expression = workflow.split("    if: >-", 1)[1].split("    runs-on:", 1)[0]
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in expression
    assert "github.event.workflow_run.head_branch == 'main'" in expression
    # A successful trusted main CI push is still the only CI-triggered recovery.
    assert re.search(
        r"\(github\.event\.workflow_run\.name == 'ci'[^)]*"
        r"github\.event\.workflow_run\.event == 'push'[^)]*"
        r"github\.event\.workflow_run\.conclusion == 'success'\)",
        expression, re.DOTALL,
    )
    # Scheduled Telegram sync may fail with an unrelated Worker HTTP 400.
    # This must not prevent the authenticated, fail-closed freshness check.
    assert re.search(
        r"\(github\.event\.workflow_run\.name == 'telegram-sync'[^)]*"
        r"github\.event\.workflow_run\.event == 'schedule'\)",
        expression, re.DOTALL,
    )
    assert not re.search(
        r"github\.event\.workflow_run\.conclusion == 'success'\s*&&\s*\(",
        expression,
    )


def test_recovery_code_still_prevents_duplicate_ingestion_when_triggered():
    workflow = Path(".github/workflows/ingestion-freshness-recovery.yml").read_text(
        encoding="utf-8"
    )
    watchdog = Path("tools/ingestion_watchdog.py").read_text(encoding="utf-8")
    assert "concurrency:" in workflow
    assert "actions: write" in workflow
    assert "persist-credentials: false" in workflow
    assert 'payload={"ref": "main", "inputs": {"dry_run": "false"}}' in watchdog
    assert '"pipeline-already-running"' in watchdog
    assert '"newer-run-without-health-checkpoint"' in watchdog
