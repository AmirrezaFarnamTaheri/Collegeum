"""Bounded read-only EURAXESS form-field probe; never changes source configuration.

Both candidate parameter names were observed in the 2026-11-03 public
EURAXESS form probe. This inspects *only* four explicit official HTTPS URLs,
through the repository's robots-aware and rate-limited client. Differentiated
results are evidence worth reviewing, never proof of relevance or availability.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from predoc_pipeline.ingest.http import PoliteClient
from tools.probe_life_sciences_sources import (
    PROBE_USER_AGENT,
    candidate_job_urls,
    search_page_evidence,
)

BASE = "https://euraxess.ec.europa.eu/jobs/search"
PATTERN = r"euraxess[.]ec[.]europa[.]eu/jobs/[0-9]+$"
PARAMETERS = ("keys", "keywords")
TERMS = ("epigenetics", "genomics")


def compare_candidate_queries(
    client: Any, *, terms: tuple[str, str] = TERMS,
) -> dict[str, Any]:
    """Return only aggregate identity and HTML evidence; no raw jobs or pages."""
    if terms != TERMS:
        raise ValueError("Only approved, fixed official research keywords can be probed")
    report: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "purpose": "read_only_official_form_parameter_diagnostics",
        "request_budget": len(PARAMETERS) * len(TERMS),
        "verified_server_side_filter": False,
        "parameters": [],
    }
    for parameter in PARAMETERS:
        rows: list[dict[str, Any]] = []
        observed: list[set[str]] = []
        for term in terms:
            url = BASE + "?" + urlencode({parameter: term})
            try:
                response = client.get(url, use_cache=False)
                if response.status == 999:
                    rows.append({"term": term, "status": "blocked_robots", "http_status": 999,
                                 "vacancy_links": 0, "declared_result_count": None})
                    continue
                if not response.ok:
                    rows.append({"term": term, "status": "http_error",
                                 "http_status": response.status, "vacancy_links": 0,
                                 "declared_result_count": None})
                    continue
                matches = candidate_job_urls(response.text, url, PATTERN)
                evidence = search_page_evidence(response.text, url)
                observed.append(matches)
                rows.append({
                    "term": term,
                    "status": "ok" if matches else "no_recognized_vacancy_links",
                    "http_status": response.status,
                    "vacancy_links": len(matches),
                    "declared_result_count": evidence["declared_result_count"],
                    "keyword_in_visible_text": evidence["keyword_in_visible_text"],
                    "search_value_reflected": evidence["search_value_reflected"],
                })
            except Exception:  # noqa: BLE001 - keep other safe observations
                rows.append({"term": term, "status": "http_error", "http_status": 0,
                             "vacancy_links": 0, "declared_result_count": None})
        complete = len(observed) == len(TERMS) and all(observed)
        signal = ("distinct_nonempty" if observed[0] != observed[1]
                  else "identical_nonempty") if complete else "indeterminate"
        combined = set().union(*observed) if observed else set()
        shared = len(observed[0] & observed[1]) if len(observed) == 2 else None
        report["parameters"].append({
            "parameter": parameter,
            "query_result_signal": signal,
            "distinct_observed_link_urls": len(combined),
            "pairwise_shared_link_urls": shared,
            "observations": rows,
        })
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only robot-aware EURAXESS query parameter comparison"
    )
    parser.add_argument(
        "--output", type=Path,
        default=Path("build/euraxess-candidate-query-parameters.json"),
    )
    args = parser.parse_args()
    with PoliteClient(
        user_agent=PROBE_USER_AGENT,
        timeout=15.0, per_host_delay=3.0, respect_robots=True,
    ) as client:
        report = compare_candidate_queries(client)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
