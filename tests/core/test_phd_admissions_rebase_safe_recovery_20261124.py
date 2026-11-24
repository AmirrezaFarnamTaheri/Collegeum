"""A long official-source run must not lose verified evidence on rebase conflict.

Main can advance during the six-minute refresh when a programme's official
source URL is repaired. Git rebase then conflicts on generated admissions
catalogue JSON. Safest recovery is to discard only the unpublished local
snapshot and re-run robots-aware verification on the new authoritative main,
not to force-push, take the old JSON, or clear source restrictions.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "phd-admissions-refresh.yml"


def test_admissions_rebase_conflict_rechecks_latest_authoritative_sources():
    body = WORKFLOW.read_text(encoding="utf-8")
    publish = body.split("name: Commit only derived public official-source observations", 1)[1]
    # Regression: run 45360602129 failed when a new source URL on main caused
    # git rebase to conflict with in-flight, freshly checked observations.
    assert "if ! git rebase origin/main" in publish
    assert "git rebase --abort" in publish
    assert "git reset --hard origin/main" in publish
    assert "python3 -S tools/update_phd_admissions.py --check" in publish
    assert (
        "python3 -S tools/update_phd_admissions.py "
        "--batch-size 40 --recheck-all-readable"
    ) in publish
    assert "python3 -S tools/update_official_calls.py --check" in publish
    assert "python3 -S tools/update_official_calls.py" in publish


def test_recovery_never_overwrites_a_new_source_with_old_observation():
    body = WORKFLOW.read_text(encoding="utf-8")
    publish = body.split("name: Commit only derived public official-source observations", 1)[1]
    # Check new main state before writing, then use a non-force push. Never
    # accept stale source provenance through a conflicted git checkout.
    assert "git fetch origin main" in publish
    assert "git rebase origin/main" in publish
    assert "git reset --hard origin/main" in publish
    assert "git diff --cached --quiet" in publish
    assert "git push origin HEAD:main" in publish
    assert "git push --force" not in publish
    assert "git checkout --ours" not in publish
    assert "git checkout --theirs" not in publish


def test_recovery_keeps_official_source_policy_and_isolated_refresh():
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "concurrency:" in body
    assert "cancel-in-progress: false" in body
    assert "tools/update_phd_admissions.py --check" in body
    assert "--recheck-all-readable" in body
    assert "tools/update_official_calls.py --check" in body
    assert "TELEGRAM_BOT_TOKEN" not in body
    assert "secrets." not in body
