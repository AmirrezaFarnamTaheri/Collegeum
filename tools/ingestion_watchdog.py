"""Fail-closed scheduled-ingestion recovery gate.

This is the *only* code allowed to issue an automatic pipeline workflow_dispatch.
It never publishes directly, modifies journals, or reads private subscriber state.
Pure decision logic is stdlib-only and covered by unit tests; network IO is
confined to the small CLI adapter at the bottom.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

STALE_AFTER = timedelta(hours=8)  # Two nominal four-hour ingestion intervals.
FUTURE_SKEW = timedelta(minutes=2)
ACTIVE_STATUSES = {"queued", "requested", "waiting", "pending", "in_progress"}
KNOWN_STATUSES = ACTIVE_STATUSES | {"completed"}
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
# Only changes that affect the public-publishing contract merit a CI-triggered
# ingestion; a dashboard, docs, test or state-only push must not send anything.
_PUBLISHER_FILES = {
    ".github/workflows/pipeline.yml",
    "config/preferences.toml",
    "src/predoc_pipeline/pipeline.py",
    "src/predoc_pipeline/routing.py",
    "src/predoc_pipeline/settings.py",
    "src/predoc_pipeline/publish/telegram.py",
}


@dataclass(frozen=True)
class Decision:
    dispatch: bool
    reason: str
    age_seconds: int | None = None


@dataclass(frozen=True)
class CadenceAudit:
    """Read-only run-creation observations, not a claim of dropped cron events."""

    verified: bool
    reason: str
    expected: int = 0
    observed: int = 0
    delayed: int = 0
    missing: int = 0
    unsettled: int = 0
    max_creation_delay_seconds: int | None = None
    missing_ticks: tuple[str, ...] = ()
    late_pending: int = 0
    late_pending_ticks: tuple[str, ...] = ()


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("Expected timezone-aware ISO 8601 timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Missing timestamp offset")
    return parsed.astimezone(UTC)


def evaluate(
    health: Any,
    runs: Any,
    *,
    now: datetime,
    stale_after: timedelta = STALE_AFTER,
) -> Decision:
    """Decide whether one automatic dispatch is safe, without side effects.

    Once an ingestion has started after the last public snapshot, this gate
    refuses automatic retries even if the run subsequently failed. That is a
    persistence/collection incident, not merely a missed cron tick.
    """
    if now.tzinfo is None or stale_after <= timedelta(0):
        raise ValueError("An aware clock and positive freshness threshold are required")
    now = now.astimezone(UTC)
    try:
        generated = _timestamp(health.get("generated_at") if isinstance(health, dict) else None)
    except (ValueError, OverflowError, TypeError):
        return Decision(False, "invalid-health-timestamp")
    if generated > now + FUTURE_SKEW:
        return Decision(False, "future-health-timestamp")
    age = max(0, int((now - generated).total_seconds()))
    if now - generated <= stale_after:
        return Decision(False, "fresh", age)

    # API read failures, truncated/empty history and malformed run objects
    # must not lead to potentially duplicated Telegram broadcasts.
    if not isinstance(runs, list) or not runs:
        return Decision(False, "untrusted-run-history", age)
    main_runs = []
    for item in runs:
        if not isinstance(item, dict):
            return Decision(False, "untrusted-run-history", age)
        if item.get("head_branch") != "main":
            continue
        try:
            created = _timestamp(item.get("created_at"))
        except (ValueError, OverflowError, TypeError):
            return Decision(False, "untrusted-run-history", age)
        status = item.get("status")
        if status not in KNOWN_STATUSES:
            return Decision(False, "untrusted-run-history", age)
        main_runs.append((created, status))

    if not main_runs:
        return Decision(False, "untrusted-run-history", age)
    if any(status in ACTIVE_STATUSES for _, status in main_runs):
        return Decision(False, "pipeline-already-running", age)
    if any(created > generated for created, _ in main_runs):
        return Decision(False, "newer-run-without-health-checkpoint", age)
    return Decision(True, "stale-without-newer-run", age)



def _publisher_revision_baseline(
    runs: Any, *, now: datetime, trigger_created_at: str, main_sha: str,
) -> str | None:
    """Find an old main pipeline SHA with no newer or pending execution."""
    if now.tzinfo is None or not _SHA.fullmatch(main_sha):
        return None
    now = now.astimezone(UTC)
    try:
        trigger_at = _timestamp(trigger_created_at)
    except (ValueError, OverflowError, TypeError):
        return None
    if trigger_at > now + FUTURE_SKEW:
        return None
    if not isinstance(runs, list) or not runs:
        return None
    main_runs: list[tuple[datetime, str, str]] = []
    for item in runs:
        if not isinstance(item, dict):
            return None
        if item.get("head_branch") != "main":
            continue
        status, sha = item.get("status"), item.get("head_sha")
        if status not in KNOWN_STATUSES or not isinstance(sha, str):
            return None
        if not _SHA.fullmatch(sha):
            return None
        try:
            created = _timestamp(item.get("created_at"))
        except (ValueError, TypeError, OverflowError):
            return None
        if created > now + FUTURE_SKEW:
            return None
        main_runs.append((created, status, sha))
    if not main_runs or any(status in ACTIVE_STATUSES for _, status, _ in main_runs):
        return None
    created, _, previous_sha = max(main_runs, key=lambda item: item[0])
    # A run created after this CI began could already be executing the new
    # publisher via checkout(ref=main), even if its event SHA looks old.
    if created >= trigger_at or previous_sha == main_sha:
        return None
    return previous_sha


def evaluate_publisher_revision(
    runs: Any,
    comparison: Any,
    *,
    now: datetime,
    trigger_created_at: str,
    main_sha: str,
) -> Decision:
    """Fail closed unless a newer tested publisher has never run on main."""
    previous_sha = _publisher_revision_baseline(
        runs, now=now, trigger_created_at=trigger_created_at, main_sha=main_sha,
    )
    if previous_sha is None:
        return Decision(False, "publisher-revision-already-covered-or-unverified")
    if not isinstance(comparison, dict) or comparison.get("status") != "ahead":
        return Decision(False, "untrusted-publisher-comparison")
    base = comparison.get("base_commit")
    if not isinstance(base, dict) or base.get("sha") != previous_sha:
        return Decision(False, "untrusted-publisher-comparison")
    files = comparison.get("files")
    if not isinstance(files, list) or not files or len(files) >= 300:
        return Decision(False, "untrusted-publisher-comparison")
    if any(not isinstance(file, dict) or
           not isinstance(file.get("filename"), str) or
           file.get("status") not in {"added", "modified", "removed", "renamed"}
           for file in files):
        return Decision(False, "untrusted-publisher-comparison")
    if not any(file["filename"] in _PUBLISHER_FILES for file in files):
        return Decision(False, "no-publisher-change")
    return Decision(True, "publisher-revision-not-ingested")


def audit_cadence(
    runs: Any, *, now: datetime, lookback: timedelta = timedelta(hours=24),
) -> CadenceAudit:
    """Compare actual schedule-triggered runs with four-hour UTC cron ticks.

    Each scheduled run maps to its preceding four-hour tick. The latest tick
    remains unsettled for one complete interval; an absent mature run is not
    proof of an Actions scheduler failure. Require run history older than the
    first expected tick so an API-limited response cannot invent gaps.
    """
    if now.tzinfo is None or lookback <= timedelta(0):
        raise ValueError("An aware clock and positive cadence lookback are required")
    now = now.astimezone(UTC)
    if not isinstance(runs, list) or not runs:
        return CadenceAudit(False, "untrusted-run-history")

    scheduled: list[datetime] = []
    all_created: list[datetime] = []
    for item in runs:
        if not isinstance(item, dict):
            return CadenceAudit(False, "untrusted-run-history")
        if item.get("head_branch") != "main":
            continue
        try:
            created = _timestamp(item.get("created_at"))
        except (ValueError, TypeError, OverflowError):
            return CadenceAudit(False, "untrusted-run-history")
        if created > now + FUTURE_SKEW:
            return CadenceAudit(False, "untrusted-run-history")
        all_created.append(created)
        if (item.get("event") == "schedule"
                and item.get("name") == "predoc-pipeline"):
            scheduled.append(created)

    start = now - lookback
    tick = start.replace(
        hour=(start.hour // 4) * 4, minute=7, second=0, microsecond=0,
    )
    if tick < start:
        tick += timedelta(hours=4)
    if not all_created or min(all_created) > tick:
        return CadenceAudit(False, "insufficient-run-history")

    expected = observed = delayed = missing = unsettled = 0
    max_delay: int | None = None
    missing_ticks: list[str] = []
    late_pending_ticks: list[str] = []
    while tick <= now:
        expected += 1
        next_tick = tick + timedelta(hours=4)
        matches = [created for created in scheduled if tick <= created < next_tick]
        if matches:
            observed += 1
            delay = max(0, int((min(matches) - tick).total_seconds()))
            max_delay = delay if max_delay is None else max(max_delay, delay)
            if delay > 30 * 60:
                delayed += 1
        elif now >= next_tick:
            missing += 1
            missing_ticks.append(tick.isoformat().replace("+00:00", "Z"))
        else:
            unsettled += 1
            if now > tick + timedelta(minutes=30):
                late_pending_ticks.append(tick.isoformat().replace("+00:00", "Z"))
        tick = next_tick
    return CadenceAudit(
        True, "unobserved-schedule-slots" if missing else "schedule-slots-observed",
        expected, observed, delayed, missing, unsettled, max_delay,
        tuple(missing_ticks), len(late_pending_ticks), tuple(late_pending_ticks),
    )


def _request(
    url: str, token: str, *, payload: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, headers=headers,
                                 method="POST" if body is not None else "GET", data=body)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            status = response.status
            raw = response.read(5 * 1024 * 1024)  # bounded API response, not vacancy HTML
    except urllib.error.HTTPError as exc:
        # Never print body, headers, URL or exception repr: they may contain
        # access tokens or other provider information.
        raise RuntimeError(f"GitHub Actions API returned HTTP {exc.code}") from None
    except (OSError, TimeoutError, urllib.error.URLError):
        raise RuntimeError("GitHub Actions API connection failed") from None
    if body is not None:
        if status != 204:
            raise RuntimeError(f"GitHub dispatch returned unexpected HTTP {status}")
        return None
    if status != 200:
        raise RuntimeError(f"GitHub runs API returned unexpected HTTP {status}")
    try:
        decoded = json.loads(raw)
    except (ValueError, UnicodeError):
        raise RuntimeError("GitHub runs API supplied invalid JSON") from None
    if not isinstance(decoded, dict):
        raise RuntimeError("GitHub runs API supplied invalid payload")
    return decoded


def _summary(
    decision: Decision, action: str, *, cadence: CadenceAudit | None = None,
) -> None:
    age = "unknown" if decision.age_seconds is None else f"{decision.age_seconds / 3600:.2f}h"
    text = f"Ingestion watchdog: {decision.reason}; published data age {age}; action: {action}"
    print(text, flush=True)
    if decision.reason not in {"fresh", "pipeline-already-running"}:
        # An operator diagnostic, never proof that a publisher has succeeded.
        print(f"::warning title=Ingestion freshness::{text}", flush=True)
    cadence_text = ""
    if cadence is not None:
        if cadence.verified:
            lag = (f"{cadence.max_creation_delay_seconds // 60}m"
                   if cadence.max_creation_delay_seconds is not None else "unknown")
            cadence_text = (
                f"scheduled slots (last 24h): {cadence.expected}; "
                f"observed: {cadence.observed}; delayed >30m: {cadence.delayed}; "
                f"unobserved mature slots: {cadence.missing}; "
                f"unsettled slots: {cadence.unsettled}; "
                f"unobserved >30m (not mature): {cadence.late_pending}; "
                f"max run-creation lag: {lag}"
            )
            print(f"Ingestion cadence: {cadence_text}", flush=True)
            if cadence.missing or cadence.late_pending:
                print(f"::warning title=Ingestion cron coverage::{cadence_text}", flush=True)
        else:
            cadence_text = f"unverified ({cadence.reason}); insufficient history for gap claims"
            print(f"Ingestion cadence: {cadence_text}", flush=True)

    report = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if report:
        with open(report, "a", encoding="utf-8") as fh:
            fh.write("### Published ingestion freshness\n\n")
            fh.write(f"- Health state: **{decision.reason}**\n")
            fh.write(f"- Age: **{age}** (threshold: 8h)\n")
            fh.write(f"- Dispatch: **{action}**\n")
            fh.write(
                "- This is not a publication success signal; "
                "check the ensuing pipeline run.\n"
            )
            if cadence is not None:
                fh.write(f"- Schedule audit: **{cadence_text}**\n")
                if cadence.verified and cadence.missing_ticks:
                    fh.write("- No scheduled run observed for mature slots: "
                             + ", ".join(cadence.missing_ticks) + "\n")
                if cadence.verified and cadence.late_pending_ticks:
                    fh.write("- Scheduled slots >30m overdue but still maturing: "
                             + ", ".join(cadence.late_pending_ticks) + "\n")
                fh.write(
                    "- Run creation timestamps do not measure job queueing or "
                    "prove GitHub dropped a cron event. Manual recovery runs "
                    "are not counted as scheduled events.\n"
                )

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dispatch", action="store_true",
                        help="Allow exactly one guarded workflow_dispatch with dry_run=false")
    parser.add_argument("--strict-cadence", action="store_true",
                        help="Fail the monitor for verified unobserved mature cron slots")
    parser.add_argument("--health", default="docs/data/health.json", type=Path)
    args = parser.parse_args(argv)

    token = os.environ.get("GH_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not _REPOSITORY.fullmatch(repo):
        print("::error::Ingestion watchdog needs a valid GitHub repository and Actions token")
        return 1
    try:
        health = json.loads(args.health.read_text(encoding="utf-8"))
        base = f"https://api.github.com/repos/{repo}/actions"
        response = _request(base + "/workflows/pipeline.yml/runs?branch=main&per_page=50", token)
        if not isinstance(response, dict) or not isinstance(response.get("workflow_runs"), list):
            raise RuntimeError("GitHub Actions run history is unavailable")
        now = datetime.now(UTC)
        runs = response["workflow_runs"]
        decision = evaluate(health, runs, now=now)
        cadence = audit_cadence(runs, now=now)
        if (decision.reason == "fresh"
                and os.environ.get("RELEASE_CHECK") == "true"
                and os.environ.get("GITHUB_SHA") == os.environ.get("CI_HEAD_SHA")):
            # This path is enabled only by trusted successful main push CI in
            # the workflow, never by an untrusted PR or scheduled sync.
            main_sha = os.environ.get("GITHUB_SHA", "")
            trigger_at = os.environ.get("CI_RUN_CREATED_AT", "")
            previous_sha = _publisher_revision_baseline(
                runs, now=now, trigger_created_at=trigger_at, main_sha=main_sha,
            )
            if previous_sha is not None:
                # GitHub compare is authoritative about whether the checked
                # in publisher changed since the last recorded ingestion.
                compare_url = (
                    f"https://api.github.com/repos/{repo}/compare/"
                    f"{previous_sha}...{main_sha}"
                )
                try:
                    comparison = _request(compare_url, token)
                except RuntimeError:
                    # Missing or malformed comparison must NEVER dispatch.
                    comparison = None
                release = evaluate_publisher_revision(
                    runs, comparison, now=now,
                    trigger_created_at=trigger_at, main_sha=main_sha,
                )
                if release.dispatch:
                    decision = Decision(
                        True, release.reason, age_seconds=decision.age_seconds,
                    )
        action = "none"
        if decision.dispatch:
            if args.dispatch:
                # The target workflow's existing predoc-bot concurrency group
                # serializes all subscriber/journal side effects.
                _request(base + "/workflows/pipeline.yml/dispatches", token,
                         payload={"ref": "main", "inputs": {"dry_run": "false"}})
                action = "requested-new-main-ingestion"
            else:
                action = "would-request-new-main-ingestion"
        _summary(decision, action, cadence=cadence)
        if args.strict_cadence and cadence.verified and cadence.missing:
            # A healthy published snapshot must not hide missing cron coverage.
            # This only changes the observer check conclusion; the normal
            # recovery dispatch guard remains unchanged and fail-closed.
            print(
                "::error title=Unobserved scheduled ingestion slots::"
                f"{cadence.missing} mature 4-hour cron slot(s) unobserved"
            )
            return 2
    except (OSError, ValueError, RuntimeError) as exc:
        # Errors are safe, synthesized messages; no remote body is exposed.
        print(f"::error::Ingestion watchdog aborted: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
