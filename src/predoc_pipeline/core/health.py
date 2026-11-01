"""Source coverage and safe public failure descriptions; stdlib only."""

from __future__ import annotations

import re
from typing import Any


def source_status(data: dict[str, Any]) -> str:
    if data.get("skipped"):
        return "skipped"
    if data.get("ok") is False or data.get("errors"):
        return "partial" if data.get("items") else "failed"
    if not data.get("items") and not data.get("unchanged"):
        # A completed fetch which unexpectedly yields zero vacancies is not
        # evidence that the feed is healthy. Small/seasonal boards may opt out.
        if data.get("fetched") and not data.get("may_be_empty", False):
            return "failed"
        return "empty"
    return "successful"


def source_summary(stats: dict[str, Any]) -> dict[str, int]:
    summary = dict.fromkeys(("total", "successful", "empty", "failed", "partial", "skipped"), 0)
    for name, data in stats.items():
        if name.startswith("_") or not isinstance(data, dict):
            continue
        status = source_status(data)
        summary["total"] += 1
        summary[status] += 1
        # Categories are mutually exclusive: partial sources are reported in
        # "partial", not also in "failed".
    return summary


def source_error_count(stats: dict[str, Any]) -> int:
    return sum(max(1, int(data.get("errors") or 0)) for name, data in stats.items()
               if not name.startswith("_") and isinstance(data, dict)
               and source_status(data) in {"failed", "partial"})


def public_failure(message: Any) -> str:
    """Publish controlled explanations, never exception bodies or request URLs.

    Exceptions may contain credentials, tokens and response data. Recognizing
    categories is safer than trying to redact every possible secret spelling.
    The original diagnostic remains available in the local/workflow log.
    """
    text = str(message or "")
    lowered = text.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "Request timed out"
    if "robots" in lowered:
        return "Access restricted by robots policy"
    match = re.search(r"(?:HTTP|status(?: code)?)\D{0,20}([45]\d\d)\b", text, re.I)
    if match:
        return f"HTTP {match.group(1)}"
    if "rate limit" in lowered or "ratelimited" in lowered:
        return "Rate limit reached"
    if "unknown board type" in lowered:
        return "Unsupported board adapter"
    if "parse" in lowered or "decode" in lowered or "invalid json" in lowered:
        return "Response could not be parsed"
    if "discovery limit" in lowered or "pagination cap" in lowered:
        return "Discovery truncated by configured limit"
    if "skipped" in lowered:
        return "Source skipped by its adapter"
    return "Source request failed"


def public_source_stats(stats: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for name, data in stats.items():
        if not isinstance(data, dict):
            continue
        # Export only collector metrics, not arbitrary extra provider payloads.
        public = {key: value for key, value in data.items() if key in {
            "kind", "items", "raw", "relevant", "new", "fetched", "errors", "ok",
            "skipped", "may_be_empty", "seconds", "unchanged", "known", "deferred", "rejected",
        }}
        # Structured, allowlisted diagnostics avoid publishing untrusted URLs or
        # exception bodies while preserving the distinction between fetch,
        # parsing and bounded-pagination failures.
        counts = data.get("failure_counts")
        if isinstance(counts, dict):
            public["failure_counts"] = {
                name: value if type(value) is int and value >= 0 else 0
                for name in ("fetch", "parse", "limit")
                for value in (counts.get(name),)
            }
        stage = data.get("failure_stage")
        if isinstance(stage, str) and stage and all(
            part in {"fetch", "parse", "limit", "timeout", "discovery"}
            for part in stage.split("/")
        ):
            public["failure_stage"] = stage
        public["messages"] = list(dict.fromkeys(
            public_failure(message) for message in (data.get("messages") or [])[:5]
        ))
        # Successful transport is not the same as healthy source coverage.
        # For example, an expected-nonempty provider may return zero postings
        # without raising. Publish an explicit derived outcome so consumers
        # don't mistake raw ok=True for a healthy source.
        public["status"] = source_status(public)
        # Expose only finite, known-safe scheduler counters and restriction
        # status. Do not export query strings, URLs or arbitrary provider text.
        search = data.get("search_diagnostics")
        if isinstance(search, dict):
            safe_ints = (
                "total_pairs", "plan_size", "requests", "completed_queries",
                "failed_requests", "pending_queries", "incomplete_queries",
                "checkpointed_queries", "replay_candidates",
                "pages_with_more_possible", "unprocessed_selected",
                "coverage_gaps", "truncated_queries", "unverified_empty",
            )
            safe_bools = (
                "access_limited", "time_budget_reached", "backpressure",
                "provider_cooldown_active",
            )
            public["search_diagnostics"] = {
                **{
                    k: search[k] for k in safe_ints
                    if type(search.get(k)) is int and 0 <= search[k] <= 1000000
                },
                **{
                    k: search[k] for k in safe_bools
                    if type(search.get(k)) is bool
                },
            }
        if (
            public["status"] == "failed"
            and not public["messages"]
            and public.get("fetched")
            and not public.get("items")
        ):
            public["messages"] = ["Unexpected empty source result"]
        out[name] = public
    return out
