"""Bounded, official B-ite German jobs listing verification; no writes."""
from __future__ import annotations

import asyncio
import json
import re

from bs4 import BeautifulSoup
from predoc_pipeline.boards.collector import build_http
from predoc_pipeline.boards.config import HttpConfig
from predoc_pipeline.ingest.http import PoliteClient

PAGE = "https://www.helmholtz-munich.de/karriere/stellenangebote"
API = "https://jobs.b-ite.com/api/v1/postings/search"
UA = "Collegeum-LSSourceProbe/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
KEY = re.compile(r'\bvar\s+apiKey\s*=\s*["\x27]([a-fA-F0-9]{40})["\x27]')
CALL = re.compile(r'api\("([^"]+)",\s*(\d+),\s*"[^"]+",\s*"([^"]+)",\s*"([^"]+)"')


async def main() -> None:
    with PoliteClient(user_agent=UA, timeout=15, per_host_delay=2,
                      respect_robots=True) as polite:
        response = polite.get(PAGE, use_cache=False)
        if not response.ok:
            raise RuntimeError("German employer listing unavailable or policy-denied")
        soup = BeautifulSoup(response.text[:950000], "lxml")
        advertised = [
            str(tag.get("data-bite-jobs-api-listing"))
            for tag in soup.select("[data-bite-jobs-api-listing]")[:5]
        ]
        print(json.dumps({"official_advertised_widgets": advertised}))
        if not advertised:
            raise RuntimeError("German employer careers page has no public B-ite widget")
        for token in advertised[:2]:
            if not token.startswith("helmholtz-zentrum-muenchen:"):
                continue
            code = token.split(":", 1)[1]
            if not re.fullmatch(r"[a-z0-9-]{2,80}", code):
                raise ValueError("Unsupported public listing identifier")
            widget = (
                "https://cs-assets.b-ite.com/helmholtz-zentrum-muenchen/"
                "jobs-api/" + code + ".js"
            )
            if not polite.allowed(widget) or not polite.allowed(API):
                raise RuntimeError("B-ite employer listing denied by robots policy")
            cfg = HttpConfig(timeout=16, max_retries=0, source_timeout=40)
            async with build_http(cfg) as http:
                script = await http.get_text(widget)
                k = KEY.search(script)
                call = CALL.search(script)
                if not k or not call:
                    raise RuntimeError("German B-ite listing has changed its public API contract")
                _, channel, category, lang = call.groups()
                payload = {
                    "key": k.group(1), "channel": int(channel),
                    "locale": lang, "sort": {"by": "title", "order": "asc"},
                    "filter": {
                        "locale": {"in": ["en", "de"]},
                        "custom.Zuordnung": {"in": [category]},
                    },
                    "origin": PAGE, "page": {"offset": 0},
                }
                data = await http.post_json(API, payload)
            if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list):
                raise RuntimeError("German B-ite search has no validated jobPostings")
            print(json.dumps({
                "widget_name": code, "locale": lang,
                "public_category": category,
                "page": data.get("page"), "count": len(data["jobPostings"]),
                "jobs": [
                    {"title": str(p.get("title", ""))[:155],
                     "url": str(p.get("url", ""))[:180],
                     "expires": p.get("endsOn")}
                    for p in data["jobPostings"][:24] if isinstance(p, dict)
                ],
            }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
