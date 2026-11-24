"""Report every Economics PhD programme's deadline coverage without network IO.

This audits stored observations, not the live university pages. A claimed
verification counts only while its full date, freshness and institutional
provenance remain valid. No source is fetched or observation promoted.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

if __package__:
    from .update_phd_admissions import (
        CHECK_INTERVAL,
        DATE_PATTERN,
        EXPIRY,
        PUBLIC,
        SEEDS,
        STATUSES,
        _institutional_url,
        _parse_date,
        _timestamp,
    )
else:
    from update_phd_admissions import (
        CHECK_INTERVAL,
        DATE_PATTERN,
        EXPIRY,
        PUBLIC,
        SEEDS,
        STATUSES,
        _institutional_url,
        _parse_date,
        _timestamp,
    )

EXPECTED_PROGRAMMES = 251
ACTION = {
    "current_deadline": "Keep the scheduled official-source recheck before the evidence expires.",
    "no_explicit_deadline": (
        "Review the current official admissions route for an explicit year and application cutoff; "
        "if none is published, retain the unconfirmed result."
    ),
    "ambiguous_deadline": (
        "Resolve the intake, applicant group or conflicting dates using the university's own pages."
    ),
    "robots_unavailable": (
        "Retry under the normal check cadence or verify an alternative official source; "
        "do not assume permission when robots instructions are unavailable."
    ),
    "robots_disallowed": "Respect the restriction and locate a permitted official source.",
    "fetch_failed": (
        "Check whether the official URL moved or needs an alternative readable university page."
    ),
    "unsafe_redirect": "Verify the university's canonical destination before changing its URL.",
    "insecure_source": "Verify and adopt the university's HTTPS programme URL.",
    "unverified": "Run the bounded official-source check for this programme.",
    "stale": "Refresh the official source before displaying a confirmed date.",
    "expired_deadline": "Find the next published application round; do not advance the year.",
    "stale_check": "Refresh the official source; the stored evidence is more than 14 days old.",
    "missing_check": "Obtain a timestamped official-source observation.",
    "future_check": "Correct the invalid future check timestamp, then verify the official source.",
    "missing_observation": "Restore the programme's observation and run its official-source check.",
    "duplicate_observation": "Reconcile duplicate observations before counting either assertion.",
    "source_mismatch": "Reconcile the seed URL and observation using the reviewed official source.",
    "invalid_deadline": "Recheck the source; a valid full calendar date is required.",
    "out_of_range_deadline": "Verify that the deadline belongs to a supported admission cycle.",
    "invalid_programme_url": "Verify and adopt the university's HTTPS programme URL.",
    "invalid_evidence_url": "Record evidence from the programme's permitted HTTPS host.",
    "unrecorded_evidence_url": "Recheck and record the university page used as date evidence.",
    "unsupported_excerpt": "Retain an excerpt containing the exact, unambiguous full deadline.",
    "unexpected_deadline": "Remove the unconfirmed date or establish current official evidence.",
    "unknown_status": "Repair the observation's unsupported verification status.",
    "catalogue_issue": "Resolve the metadata issues before treating catalogue claims as confirmed.",
}


def _identity(row: dict) -> tuple[str, str]:
    return row.get("institution", ""), row.get("country_code", "")


def _day(value: object) -> date | None:
    if not isinstance(value, str) or re.fullmatch(r"20\d{2}-\d{2}-\d{2}", value) is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def audit_catalogues(seeds: dict, public: dict, *, now: datetime) -> dict:
    """Return a deterministic inventory; preserve one report row per seed.

    The collector remains responsible for programme and date-role context.
    Here its stored excerpt must still contain the exact unambiguous date.
    Reusing a funding-only excerpt gate would incorrectly reject supported
    admissions tables, date-before-label layouts and grouped programme lists.
    """
    if now.tzinfo is None:
        raise ValueError("The audit time must include a timezone")
    now = now.astimezone(UTC)
    if not isinstance(seeds, dict) or not isinstance(public, dict):
        raise ValueError("Catalogues must be objects")
    leads, observations = seeds.get("programmes"), public.get("programmes")
    if not isinstance(leads, list) or not isinstance(observations, list):
        raise ValueError("Catalogues must contain programme lists")
    if any(not isinstance(row, dict) for row in leads + observations):
        raise ValueError("Programme records must be objects")
    keys = [_identity(row) for row in leads]
    if any(not all(isinstance(v, str) and v for v in key) for key in keys):
        raise ValueError("Every seed needs an institution and country code")
    if len(set(keys)) != len(keys):
        raise ValueError("Seed identities must be unique")

    metadata_issues = []
    if seeds.get("kind") != "economics_phd_admissions_seeds":
        metadata_issues.append("invalid_seed_kind")
    if public.get("kind") != "economics_phd_admissions_observations":
        metadata_issues.append("invalid_observation_kind")
    if public.get("scope") != "official_programme_sources_only":
        metadata_issues.append("invalid_source_scope")
    if not isinstance(public.get("source"), dict) or public["source"].get(
        "deadline_values_reused"
    ) is not False:
        metadata_issues.append("untrusted_upstream_dates")
    if len(leads) < EXPECTED_PROGRAMMES:
        metadata_issues.append("unexpected_programme_count")
    generated = _timestamp(public.get("generated_at"))
    if generated is None or generated > now:
        metadata_issues.append("invalid_catalogue_timestamp")

    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in observations:
        key = _identity(row)
        if not all(isinstance(value, str) for value in key):
            raise ValueError("Observation identities must be strings")
        by_key[key].append(row)
    extras = sorted(set(by_key) - set(keys))
    if extras:
        metadata_issues.append("observations_outside_seed_inventory")

    programmes = []
    for seed in leads:
        matches = by_key.get(_identity(seed), [])
        row = matches[0] if matches else {}
        status = row.get("status")
        issues = []
        if not matches:
            issues.append("missing_observation")
        elif len(matches) != 1:
            issues.append("duplicate_observation")
        lead_url = seed.get("official_programme_url")
        if not isinstance(lead_url, str) or (
            _institutional_url(lead_url, lead_url, for_provenance=True) is None
        ):
            issues.append("invalid_programme_url")
        if matches and row.get("official_programme_url") != lead_url:
            issues.append("source_mismatch")
        if not isinstance(status, str) or status not in STATUSES:
            issues.append("unknown_status")
        elif status != "verified":
            issues.append(status)
            if row.get("deadline_iso") is not None:
                issues.append("unexpected_deadline")
        checked = _timestamp(row.get("checked_at"))
        if checked is None:
            issues.append("missing_check")
        elif checked > now:
            issues.append("future_check")
        elif now - checked > EXPIRY:
            issues.append("stale_check")

        sources = row.get("investigated_urls")
        sources = sources if isinstance(sources, list) else []
        reviewed = sorted({
            source for source in sources if isinstance(source, str)
            and isinstance(lead_url, str)
            and _institutional_url(source, lead_url, for_provenance=True) is not None
        })
        if status == "verified":
            deadline = _day(row.get("deadline_iso"))
            if deadline is None:
                issues.append("invalid_deadline")
            elif deadline < now.date():
                issues.append("expired_deadline")
            elif deadline > date(now.year + 2, 12, 31):
                issues.append("out_of_range_deadline")
            evidence = row.get("evidence_url")
            if not isinstance(evidence, str) or not isinstance(lead_url, str) or (
                _institutional_url(evidence, lead_url, for_provenance=True) is None
            ):
                issues.append("invalid_evidence_url")
            elif evidence not in reviewed:
                issues.append("unrecorded_evidence_url")
            excerpt = row.get("evidence_excerpt")
            printed_dates = set()
            if isinstance(excerpt, str) and 0 < len(excerpt) <= 500:
                printed_dates = {
                    parsed for match in DATE_PATTERN.finditer(excerpt)
                    if (parsed := _parse_date(match)) is not None
                }
            if deadline is None or deadline not in printed_dates:
                issues.append("unsupported_excerpt")

        if metadata_issues:
            issues.append("catalogue_issue")
        reason = issues[0] if issues else "current_deadline"
        programmes.append({
            "institution": seed["institution"],
            "country_code": seed["country_code"],
            "official_programme_url": lead_url,
            "status": status,
            "current_deadline_confirmed": not issues and not metadata_issues,
            "reason": reason,
            "issues": issues,
            "next_action": ACTION[reason],
            "checked_at": row.get("checked_at"),
            "next_scheduled_check_due_at": (
                (checked + CHECK_INTERVAL).isoformat(timespec="seconds").replace("+00:00", "Z")
                if checked is not None else None
            ),
            "deadline_iso": row.get("deadline_iso"),
            "evidence_url": row.get("evidence_url"),
            "evidence_excerpt": row.get("evidence_excerpt"),
            "reviewed_source_count": len(reviewed),
            "investigated_urls": reviewed,
            "extractor_revision": row.get("extractor_revision"),
        })
    confirmed = sum(row["current_deadline_confirmed"] for row in programmes)
    return {
        "kind": "economics_phd_admissions_coverage_audit",
        "audited_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "catalogue_generated_at": public.get("generated_at"),
        "scope": "stored_evidence_only_no_network",
        "metadata_issues": metadata_issues,
        "unexpected_observations": [dict(institution=k[0], country_code=k[1]) for k in extras],
        "summary": {
            "total_programmes": len(programmes),
            "current_confirmed_deadlines": confirmed,
            "remaining_programmes": len(programmes) - confirmed,
            "all_programmes_have_current_deadlines": (
                len(programmes) == len(leads) and confirmed == len(leads)
            ),
            "programmes_with_reviewed_sources": sum(
                bool(r["reviewed_source_count"]) for r in programmes
            ),
            "reviewed_source_count": sum(r["reviewed_source_count"] for r in programmes),
            "status_counts": dict(sorted(Counter(
                r["status"] if isinstance(r["status"], str) else "missing"
                for r in programmes
            ).items())),
            "reason_counts": dict(sorted(Counter(r["reason"] for r in programmes).items())),
        },
        "programmes": programmes,
    }


def text_report(report: dict) -> str:
    summary = report["summary"]
    lines = [
        f"Economics PhD admissions coverage at {report['audited_at']}",
        "Stored-evidence audit only; no university pages were fetched.",
        f"{summary['current_confirmed_deadlines']} of {summary['total_programmes']} "
        f"programmes have current, supported deadlines; {summary['remaining_programmes']} remain.",
        "",
    ]
    if report["metadata_issues"]:
        lines += ["Catalogue issues: " + ", ".join(report["metadata_issues"]), ""]
    for reason, count in summary["reason_counts"].items():
        lines.append(f"{reason}: {count}")
        lines.append(f"  Next action: {ACTION[reason]}")
        for row in report["programmes"]:
            if row["reason"] == reason:
                lines.append(
                    f"  {row['institution']} ({row['country_code']}) | "
                    f"{row['deadline_iso'] or 'no confirmed date'} | "
                    f"{row['reviewed_source_count']} reviewed sources | "
                    f"{row['official_programme_url']}"
                )
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=Path, default=SEEDS)
    parser.add_argument("--catalogue", type=Path, default=PUBLIC)
    parser.add_argument("--now", help="Timezone-aware ISO timestamp for a reproducible audit")
    parser.add_argument("--json", action="store_true", help="Emit the complete JSON report")
    parser.add_argument(
        "--require-all-verified", action="store_true",
        help="Exit 1 unless all catalogued programmes have valid current deadline evidence",
    )
    args = parser.parse_args(argv)
    now = _timestamp(args.now) if args.now else datetime.now(UTC)
    if now is None:
        parser.error("--now must be an ISO timestamp with a timezone")
    try:
        report = audit_catalogues(
            json.loads(args.seeds.read_text(encoding="utf-8")),
            json.loads(args.catalogue.read_text(encoding="utf-8")), now=now,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else text_report(report))
    return int(args.require_all_verified and not report["summary"][
        "all_programmes_have_current_deadlines"
    ])


if __name__ == "__main__":
    sys.exit(main())
