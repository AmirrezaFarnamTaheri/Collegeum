"""Read-only Jobvision source acceptance against real public sitemap and pages.

Never publishes or writes private subscriber state. Tests complete collection
only after the public robots-aware transport accepts every requested URL.
"""
from __future__ import annotations

import json

from predoc_pipeline.ingest.http import PoliteClient
from predoc_pipeline.ingest.jobvision import collect_jobvision


def main() -> None:
    with PoliteClient(
        user_agent="Collegeum-CareerProbe/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)",
        timeout=18, per_host_delay=2, respect_robots=True,
    ) as client:
        jobs, fetched = collect_jobvision(client, max_details=8)
    report = {
        "source": "Jobvision", "fetched": fetched,
        "accepted_current_target_roles": len(jobs),
        "urls": [job["url"] for job in jobs],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if fetched < 2:
        raise RuntimeError("Jobvision did not expose discoverable vacancy IDs")


if __name__ == "__main__":
    main()
