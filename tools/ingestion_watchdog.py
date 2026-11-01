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
                and item.get("name", "predoc-pipeline") == "predoc-pipeline"):
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
        tick = next_tick
    return CadenceAudit(
        True, "unobserved-schedule-slots" if missing else "schedule-slots-observed",
        expected, observed, delayed, missing, unsettled, max_delay,
        tuple(missing_ticks),
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
                f"unsettled slots: {cadence.unsettled}; max run-creation lag: {lag}"
            )
            print(f"Ingestion cadence: {cadence_text}", flush=True)
            if cadence.missing:
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
                fh.write(
                    "- Run creation timestamps do not measure job queueing or "
                    "prove GitHub dropped a cron event. Manual recovery runs "
                    "are not counted as scheduled events.\n"
                )

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dispatch", action="store_true",
                        help="Allow exactly one guarded workflow_dispatch with dry_run=false")
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
        decision = evaluate(health, response["workflow_runs"], now=now)
        cadence = audit_cadence(response["workflow_runs"], now=now)
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
    except (OSError, ValueError, RuntimeError) as exc:
        # Errors are safe, synthesized messages; no remote body is exposed.
        print(f"::error::Ingestion watchdog aborted: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
