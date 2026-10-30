"""Read-only acceptance: official Helmholtz B-ite through Collegeum's PhD collector.

The vacancy index includes general staff roles, so this verifies the source
works without claiming any of those roles are doctoral advertisements.
No subscriber state, Telegram credentials or publication writes are used.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date
from pathlib import Path

from predoc_pipeline.boards.config import HttpConfig
from predoc_pipeline.ingest.http import PoliteClient
from predoc_pipeline.ingest.life_sciences import classify_post, discover, load_life_sources

NAME = "life_special_de_helmholtz_munich"
API = "https://jobs.b-ite.com/api/v1/postings/search"
UA = "Collegeum-LSSourceProbe/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
JOB = re.compile(r"https://jobs\.helmholtz-muenchen\.de/jobposting/[a-f0-9]{40}/?$", re.I)


async def main() -> None:
    source = next(
        s for s in load_life_sources(Path("config/life_sciences.toml"))
        if s.name == NAME
    )
    if not source.enabled or source.type != "helmholtz_bite_jobs":
        raise RuntimeError("Official Helmholtz source is not enabled as the verified adapter")
    with PoliteClient(
        user_agent=UA, timeout=15, per_host_delay=2, respect_robots=True,
    ) as polite:
        permitted = {
            url: polite.allowed(url) for url in (
                source.opt("widget_url"), source.opt("origin"), API,
            )
        }
    if not all(permitted.values()):
        raise RuntimeError("Official Helmholtz recruitment feed denied by robots policy")

    diagnostics = {}
    posts, errors = await discover(
        Path("config/life_sciences.toml"),
        HttpConfig(timeout=15, max_retries=0, source_timeout=45),
        selected_names={NAME}, diagnostics=diagnostics,
    )
    status = diagnostics.get(NAME, {})
    accepted = [v for post in posts if (v := classify_post(post, today=date.today()))]
    result = {
        "source": NAME,
        "diagnostic_status": status.get("status"),
        "errors": errors,
        "index_vacancies": len(posts),
        "doctoral_title_candidates": status.get("doctoral_candidates"),
        "eligible_life_sciences_phd": len(accepted),
        "sample_urls": [p.url for p in posts[:10]],
        "sample_deadlines": [
            p.deadline.isoformat() if p.deadline else None for p in posts[:10]
        ],
        "policy_allowed": permitted,
        "no_publication_performed": True,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors or status.get("status") not in {"discovered", "verified_empty"}:
        raise RuntimeError("Helmholtz collector failed or returned an unverified empty index")
    if not all(JOB.fullmatch(p.url) for p in posts):
        raise RuntimeError("Helmholtz vacancy has no stable official jobposting identity")
    if not posts and status.get("status") != "verified_empty":
        raise RuntimeError("No vacancies without the provider's explicit zero-total evidence")
    if any(v.get("source") != NAME for v in accepted):
        raise RuntimeError("Cross-provider Life Sciences source identity in eligible positions")


if __name__ == "__main__":
    asyncio.run(main())
