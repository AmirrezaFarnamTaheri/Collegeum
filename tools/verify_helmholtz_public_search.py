"""Probe the exact *public* B-ite search API advertised by Helmholtz Munich.

One bounded POST to a read-only recruitment search; no logins, applications,
subscriber reads or journal writes. Public client key is read from the
institution's published widget, not committed to this repository.
"""
from __future__ import annotations

import asyncio
import json
import re

from predoc_pipeline.boards.collector import build_http
from predoc_pipeline.boards.config import HttpConfig
from predoc_pipeline.ingest.http import PoliteClient

WIDGET = "https://cs-assets.b-ite.com/helmholtz-zentrum-muenchen/jobs-api/main-listing-en.js"
API = "https://jobs.b-ite.com/api/v1/postings/search"
ORIGIN = "https://www.helmholtz-munich.de/en/career/jobs"
KEY = re.compile(r'\bvar\s+apiKey\s*=\s*["\x27]([a-fA-F0-9]{40})["\x27]')
UA = "Collegeum-LSSourceProbe/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)"


async def main() -> None:
    with PoliteClient(user_agent=UA, timeout=13, per_host_delay=2,
                      respect_robots=True) as polite:
        allowed = {url: polite.allowed(url) for url in (WIDGET, API)}
    if not all(allowed.values()):
        raise RuntimeError("Public B-ite widget or search is denied by robots.txt")
    cfg = HttpConfig(timeout=16, max_retries=0, source_timeout=45)
    async with build_http(cfg) as http:
        public_script = await http.get_text(WIDGET)
        match = KEY.search(public_script)
        if not match:
            raise RuntimeError("Public widget no longer declares a supported client key")
        payload = {
            "key": match.group(1), "channel": 0, "locale": "en",
            "sort": {"by": "title", "order": "asc"},
            "filter": {
                "locale": {"in": ["en", "de"]},
                "custom.Zuordnung": {"in": ["Homepage_englisch"]},
            },
            "origin": ORIGIN,
            "page": {"offset": 0},
        }
        try:
            data = await http.post_json(API, payload)
        except Exception as exc:
            print(json.dumps({
                "source": "helmholtz_munich",
                "network_error_type": type(exc).__name__,
                "error_summary": str(exc)[:160],
                "allowed": allowed,
            }))
            raise
    if not isinstance(data, dict):
        raise RuntimeError("B-ite public search did not return an object")
    entries = data.get("jobPostings")
    page = data.get("page")
    result = {
        "source": "helmholtz_munich",
        "allowed": allowed,
        "response_keys": list(data)[:25],
        "page": page,
        "job_count": len(entries) if isinstance(entries, list) else None,
        "sample": [
            {
                "title": str(row.get("title", ""))[:140],
                "url": str(row.get("url", ""))[:220],
                "id_length": len(str(row.get("id", ""))),
                "startsOn": row.get("startsOn"),
                "endsOn": row.get("endsOn"),
                "custom_keys": list(row.get("custom", {}))[:14]
                    if isinstance(row.get("custom"), dict) else [],
            }
            for row in (entries if isinstance(entries, list) else [])[:16]
            if isinstance(row, dict)
        ],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
