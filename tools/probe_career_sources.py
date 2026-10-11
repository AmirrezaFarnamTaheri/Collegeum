"""On-demand, bounded verification of public career-provider response formats.

Run in a trusted shell with PYTHONPATH=src. Never writes Telegram subscriber
state and never downloads job detail pages. Source access and robots.txt are
handled by the existing PoliteClient; results contain counts, not page bodies.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from predoc_pipeline.ingest.career import (
    IRANTALENT_URL,
    REMOTE_API,
    iran_search_url,
    parse_iran_jobs,
    parse_irantalent_jobs,
    parse_remote_jobs,
)
from predoc_pipeline.ingest.http import PoliteClient
from predoc_pipeline.settings import Settings


def probe_sources(client: Any, *, slot: int = 0) -> dict[str, Any]:
    """Check the published endpoint and basic parsing of all three providers."""
    urls = {
        "jobicy": REMOTE_API,
        "jobinja": iran_search_url(slot),
        "irantalent": IRANTALENT_URL,
    }
    output: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "sources": {},
    }
    for source, url in urls.items():
        response = client.get(url, use_cache=False)
        entry: dict[str, Any] = {
            "status": "error", "http_status": getattr(response, "status", 0),
            "recognized": False, "matched": 0,
        }
        if not response.ok:
            entry["status"] = (
                "blocked_by_robots" if response.status == 999 else "unavailable"
            )
        else:
            text = response.text
            try:
                if source == "jobicy":
                    parsed = json.loads(text)
                    if not isinstance(parsed, dict) or not isinstance(parsed.get("jobs"), list):
                        raise ValueError("Unexpected Jobicy payload")
                    recognized = True
                    matches = parse_remote_jobs(parsed)
                elif source == "jobinja":
                    recognized = bool(re.search(
                        r"/companies/[^/\"'\s]+/jobs/[^/\"'\s]+", text,
                    ))
                    matches = parse_iran_jobs(text)
                else:
                    recognized = bool(re.search(
                        r"/(?:en|fa)/job/[^/\"'\s]+/[1-9]\d{3,10}",
                        text,
                    ))
                    matches = parse_irantalent_jobs(text)
                entry["recognized"] = recognized
                entry["matched"] = len(matches)
                entry["status"] = (
                    "matched" if matches else "healthy_empty" if recognized else "schema_changed"
                )
            except (TypeError, ValueError):
                entry["status"] = "schema_changed"
        output["sources"][source] = entry
    output["healthy"] = all(
        entry["status"] in ("matched", "healthy_empty")
        for entry in output["sources"].values()
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("build/career-probe.json"))
    args = parser.parse_args()
    settings = Settings()
    with PoliteClient(
        user_agent=settings.http_user_agent,
        timeout=settings.http_timeout_seconds,
        per_host_delay=settings.per_host_delay_seconds,
        respect_robots=settings.respect_robots_txt,
    ) as client:
        result = probe_sources(client)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["healthy"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
