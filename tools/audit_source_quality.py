"""Read-only public-source and career-vacancy evidence audit.

Produces aggregate diagnostics only. Collection, outbound requests, subscription
state, publication receipts, credentials, and source journals are untouched.
A source being fetched or a provider's active flag does not independently
verify an open or funded vacancy.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

STATUS_FIELDS = ("successful", "empty", "failed", "partial", "skipped")


def _object(root: Path, path: str) -> dict[str, Any]:
    value = json.loads((root / path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _records(root: Path, path: str) -> list[dict[str, Any]]:
    output = []
    for line in (root / path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"Expected an object record in {path}")
        output.append(item)
    return output


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.astimezone(UTC) if date.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _safe_link(value: Any) -> bool:
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme in ("http", "https") and bool(parsed.hostname)
                and not parsed.username and not parsed.password and parsed.port != 0)
    except ValueError:
        return False


def _counts(items: Any) -> dict[str, int]:
    if not isinstance(items, dict):
        raise ValueError("Source health status counts must be a map")
    numbers = {}
    for k in ("total", *STATUS_FIELDS):
        value = items.get(k, 0)
        if type(value) is not int or value < 0:
            raise ValueError("Invalid nonnegative source health count")
        numbers[k] = value
    return numbers


def audit(root: Path, *, now: datetime | None = None,
          expected_run_id: str = "") -> dict[str, Any]:
    """Return safe aggregate facts plus explicit structural/operational findings.

    In particular, never merge rotating history with latest-run summaries.
    An aged observation or elapsed deadline is not proof of a closed vacancy.
    """
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        raise ValueError("Audit clock must be timezone-aware")
    clock = clock.astimezone(UTC)
    health = _object(root, "docs/data/health.json")
    career_health = _object(root, "data/career_health.json")
    life_health = _object(root, "data/life_sources_health.json")
    dashboard = _object(root, "docs/data/listings.json")
    career_rows = _records(root, "data/career_jobs.ndjson")
    findings: set[str] = set()
    observations: set[str] = set()

    last_run = health.get("last_run")
    if not isinstance(last_run, dict):
        raise ValueError("No last_run object in public health")
    general_sources = _counts(last_run.get("sources"))
    published_sources = _counts(health.get("source_summary"))
    if (general_sources != published_sources
            or general_sources["total"] != sum(general_sources[k] for k in STATUS_FIELDS)):
        findings.add("general:source-count-mismatch")
    generated = _instant(health.get("generated_at"))
    if generated is None:
        findings.add("general:invalid-health-timestamp")
    if generated and generated > clock + timedelta(minutes=2):
        findings.add("general:health-time-in-future")
    if generated and clock - generated > timedelta(hours=8):
        observations.add("general:published-health-over-8h")
    if general_sources["failed"] or general_sources["partial"]:
        observations.add("general:degraded-sources")
    if general_sources["skipped"]:
        observations.add("general:skipped-sources")
    current_run_id = str(last_run.get("run_id") or "")
    if expected_run_id and current_run_id != expected_run_id:
        observations.add("general:trigger-run-without-matching-checkpoint")

    career_source_rows = career_health.get("sources")
    if not isinstance(career_source_rows, dict):
        raise ValueError("Career source-health map missing")
    statuses = Counter()
    blocked_without_fetch = rechecks = 0
    for entry in career_source_rows.values():
        if not isinstance(entry, dict):
            raise ValueError("Malformed career source-health entry")
        state = str(entry.get("status") or "unknown")
        statuses[state] += 1
        if state == "blocked_robots":
            blocked_without_fetch += int(entry.get("fetched") == 0)
            rechecks += int(_instant(entry.get("next_robots_check_at")) is not None)
    if statuses.get("blocked_robots", 0):
        observations.add("career:blocked-by-site-policy")
    if statuses.get("failed", 0) or statuses.get("partial", 0):
        observations.add("career:degraded-providers")

    keys = Counter(str(x.get("key") or "") for x in career_rows)
    urls = Counter(str(x.get("url") or "") for x in career_rows)
    duplicate_keys = sum(v - 1 for v in keys.values() if v > 1)
    duplicate_urls = sum(v - 1 for v in urls.values() if v > 1)
    unsafe = sum(not _safe_link(x.get("url")) for x in career_rows)
    if duplicate_keys or not all(keys):
        findings.add("career:duplicate-keys" if duplicate_keys else "career:missing-keys")
    if unsafe:
        findings.add("career:unsafe-application-urls")
    if duplicate_urls:
        observations.add("career:duplicate-application-urls-need-identity-review")

    availability = {"unknown": 0, "provider_marked_active": 0, "closed": 0}
    funding_unverified = 0
    deadline_missing = deadline_elapsed = seen_old = seen_invalid = 0
    types = Counter()
    for item in career_rows:
        status = str(item.get("availability") or "unknown").lower()
        label = "provider_marked_active" if status == "active" else (
            "closed" if status == "closed" else "unknown")
        availability[label] += 1
        funding_unverified += int(item.get("funding_status") != "verified")
        types[str(item.get("category") or "unspecified")] += 1
        last_seen = _instant(item.get("last_seen_at") or item.get("first_seen_at"))
        if last_seen is None:
            seen_invalid += 1
        elif clock - last_seen > timedelta(days=7):
            seen_old += 1
        deadline = item.get("deadline")
        if not deadline:
            deadline_missing += 1
        elif isinstance(deadline, str):
            try:
                deadline_elapsed += int(datetime.fromisoformat(deadline[:10]).date() < clock.date())
            except ValueError:
                pass
    if availability["unknown"]:
        observations.add("career:availability-not-independently-verified")
    if funding_unverified:
        observations.add("career:funding-unverified")

    life_observations = life_health.get("sources")
    latest_life = life_health.get("summary_this_run")
    if not isinstance(life_observations, dict) or not isinstance(latest_life, dict):
        raise ValueError("Life source health maps missing")
    seen_statuses = Counter()
    historical_partial = 0
    checked_at = _instant(life_health.get("checked_at"))
    if checked_at is None:
        findings.add("life:invalid-check-timestamp")
    for item in life_observations.values():
        if not isinstance(item, dict):
            raise ValueError("Malformed life source-health entry")
        status = str(item.get("status") or "unknown")
        seen_statuses[status] += 1
        if status in ("partial", "failed") and _instant(item.get("last_checked_at")) != checked_at:
            historical_partial += 1
    checked_count = life_health.get("checked_this_run")
    if type(checked_count) is not int or checked_count < 0:
        raise ValueError("Invalid life source check count")
    if (any(type(v) is not int or v < 0 for v in latest_life.values())
            or sum(latest_life.values()) != checked_count):
        findings.add("life:latest-run-count-mismatch")
    if historical_partial:
        observations.add("life:historic-partial-observations")
    if latest_life.get("partial", 0) or latest_life.get("failed", 0):
        observations.add("life:latest-run-degraded")
    catalogue = life_health.get("catalogue")
    if not isinstance(catalogue, dict):
        raise ValueError("Life source catalogue missing")
    if (any(type(catalogue.get(k)) is not int for k in ("total", "enabled", "disabled"))
            or catalogue["total"] != catalogue["enabled"] + catalogue["disabled"]):
        findings.add("life:catalogue-count-mismatch")

    public = dashboard.get("listings")
    if not isinstance(public, list) or any(not isinstance(x, dict) for x in public):
        raise ValueError("Dashboard listing records missing or malformed")
    public_ids = [str(x.get("id") or "") for x in public]
    if len(set(public_ids)) != len(public_ids) or not all(public_ids):
        findings.add("public:duplicate-or-missing-ids")
    roles = Counter(str(x.get("kind") or "unspecified") for x in public)
    unknown_visas = sum(str(x.get("visa") or "unknown") == "unknown" for x in public)
    missing_public_deadlines = sum(not x.get("deadline") for x in public)
    bad_public_links = sum(not _safe_link(x.get("apply_url")) for x in public)
    if bad_public_links:
        findings.add("public:unsafe-application-urls")

    return {
        "schema_version": 1,
        "audited_at": clock.isoformat().replace("+00:00", "Z"),
        "general": {
            "published_at": health.get("generated_at"), "run_id": current_run_id,
            "trigger_checkpoint_matches": not expected_run_id or current_run_id == expected_run_id,
            "outcome": str(last_run.get("outcome") or "unknown"),
            "sources": general_sources,
            "source_errors": last_run.get("source_errors", 0),
        },
        "career": {
            "rows": len(career_rows), "categories": dict(sorted(types.items())),
            "availability": availability, "verified_open_count": 0,
            "funding_unverified": funding_unverified,
            "deadline_missing": deadline_missing,
            "deadline_elapsed_not_proof_closed": deadline_elapsed,
            "last_seen_older_than_7d": seen_old,
            "last_seen_missing_or_invalid": seen_invalid,
            "duplicate_key_rows": duplicate_keys,
            "duplicate_url_rows": duplicate_urls,
            "unsafe_application_url_rows": unsafe,
        },
        "career_sources": {
            "checked_at": career_health.get("checked_at"),
            "statuses": dict(sorted(statuses.items())),
            "blocked_without_fetch": blocked_without_fetch,
            "next_policy_rechecks_known": rechecks,
        },
        "life_sciences": {
            "checked_at": life_health.get("checked_at"),
            "catalogue": {k: catalogue.get(k) for k in ("total", "enabled", "disabled")},
            "checked_this_run": checked_count,
            "summary_this_run": latest_life,
            "observation_statuses": dict(sorted(seen_statuses.items())),
            "historical_partial_observations": historical_partial,
        },
        "public_dashboard": {
            "visible_listings": len(public), "roles": dict(sorted(roles.items())),
            "visa_unknown": unknown_visas, "deadlines_missing": missing_public_deadlines,
        },
        "integrity_findings": sorted(findings),
        "operational_observations": sorted(observations),
        "limitations": [
            "read-only offline audit: no direct application-URL availability verification",
            "provider-marked active is not independently verified open",
            "absence of a deadline is unknown; elapsed deadline is not proof of closure",
            "rotating life source observations were not checked in the same run",
            "historical records and publication receipts were not modified",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true",
                        help="Fail only on structural integrity problems, not provider outages")
    parser.add_argument("--expected-run-id", default="", help="Optional completed pipeline run ID")
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, expected_run_id=args.expected_run_id)
    except (OSError, ValueError, TypeError):
        # Paths/URLs from payloads must never be printed to Actions logs.
        print("::error::Source-quality audit rejected missing or malformed committed inputs")
        return 1
    report = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    print(report, end="")
    if result["integrity_findings"] and args.strict:
        print("::error::Source-quality structural integrity findings require investigation")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
