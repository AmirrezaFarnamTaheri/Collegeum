"""Four-request, policy-aware official employer vacancy probe.

A public employer requisition is a *candidate*, not independently verified
currently open, funded, doctoral, or a suitable Collegeum listing. This
probe never alters source enablement, journals, or Telegram receipts.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.ingest.http import PoliteClient
from tools.probe_life_sciences_sources import candidate_job_urls

REGISTRY = Path("config/sources.toml")
REPORT = Path("build/official-predoc-requisitions.json")
PROBES = (
    (
        "princeton_rpde_jobs",
        "https://rpde.princeton.edu/opportunities/jobs",
        "https://research-princeton.icims.com/jobs/22348/"
        "senior-research-specialist/job?in_iframe=1",
        "22348",
        "2026-22348",
        r"^https://(?:main-princeton|research-princeton)\.icims\.com/jobs/[0-9]+/[^?#]+",
    ),
    (
        "brookings_jobs",
        "https://careers-brookings.icims.com/jobs/search?hashed=-435682078&ss=1",
        "https://careers-brookings.icims.com/jobs/3923/"
        "research-assistant%2C-economic-studies/job",
        "3923",
        "2026-3923",
        r"^https://careers-brookings\.icims\.com/jobs/[0-9]+/[^?#]+",
    ),
)


def _status(response: Any) -> str:
    if response.status == 999:
        return "blocked_robots"
    if not response.ok:
        return "http_error"
    return "ok"


def _safe_get(client: Any, url: str) -> Any:
    try:
        return client.get(url, use_cache=False)
    except Exception:  # noqa: BLE001 - never serialize provider error bodies
        return type("FailedResponse", (), {"status": 0, "ok": False, "text": ""})()


def probe_candidates(client: Any, registry: Path = REGISTRY) -> dict[str, Any]:
    """Inspect exactly two known disabled employer sources, four fixed URLs."""
    known = {source.name: source for source in load_board_sources(registry)}
    for name, index, _, _, _, _ in PROBES:
        source = known.get(name)
        if (source is None or source.enabled or source.type != "link_scan"
                or source.opt("url") != index):
            raise ValueError("Official candidate source configuration changed")

    report: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "purpose": "read_only_official_employer_candidate_validation",
        "request_budget": 4,
        "publishes_vacancies": False,
        "changes_source_configuration": False,
        "verified_open_positions": 0,
        "sources": {},
    }
    for name, index, detail, number, label, pattern in PROBES:
        source = known[name]
        index_result = _safe_get(client, index)
        detail_result = _safe_get(client, detail)
        index_status = _status(index_result)
        detail_status = _status(detail_result)
        candidates: set[str] = set()
        if index_status == "ok":
            candidates = candidate_job_urls(index_result.text, index, pattern)
            if not candidates:
                index_status = "unverified_empty"
        exact_index_link = any(
            re.match(r"^/jobs/" + re.escape(number) + r"/", urlsplit(url).path)
            for url in candidates
        )
        evidence_visible = False
        if detail_status == "ok":
            visible_text = BeautifulSoup(
                detail_result.text[:400_000], "lxml"
            ).get_text(" ", strip=True)
            evidence_visible = bool(re.search(
                r"(?<![0-9])" + re.escape(label) + r"(?![0-9])", visible_text
            ))
        report["sources"][name] = {
            "source_enabled": source.enabled,
            "index_status": index_status,
            "index_http_status": index_result.status,
            "index_recognized_links": len(candidates),
            "index_exact_requisition_link_observed": exact_index_link,
            "detail_status": detail_status,
            "detail_http_status": detail_result.status,
            "requisition_label_visible_in_detail": evidence_visible,
            "verified_open": False,
            "verified_funding": False,
            "needs_employer_eligibility_review": True,
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPORT)
    args = parser.parse_args()
    with PoliteClient(
        user_agent=(
            "CollegeumEmployerSourceProbe/1.0 "
            "(+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
        ),
        timeout=15.0, per_host_delay=3.0, respect_robots=True,
    ) as client:
        result = probe_candidates(client)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
