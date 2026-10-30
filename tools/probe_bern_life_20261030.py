"""Read-only inspection of official University of Bern doctoral recruitment.

No dynamic APIs, hidden credentials, partner data, publication, or subscriber
state. Each URL passes a robots-aware, rate-limited public GET.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from predoc_pipeline.ingest.http import PoliteClient

URLS = [
    "https://jobs.unibe.ch/",
    "https://jobs.unibe.ch/job-vacancies/",
    "https://karriere.unibe.ch/",
    "https://www.unibe.ch/university/organization/careers/job_vacancies/index_eng.html",
]
PATTERN = re.compile(r"/job-vacancies/[^?#]+/[a-f0-9]{8}-", re.I)


def main() -> None:
    report = {}
    with PoliteClient(
        user_agent="Collegeum-LifeSourceReview/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)",
        timeout=15, per_host_delay=3, respect_robots=True,
    ) as client:
        for url in URLS:
            res = client.get(url, use_cache=False)
            row = {"status": res.status, "error": res.error[:120],
                   "response_bytes": len(res.content)}
            if res.ok:
                soup = BeautifulSoup(res.text[:500000], "lxml")
                anchors = soup.select("a[href]")
                jobs = [
                    {"text": anchor.get_text(" ", strip=True)[:120],
                     "url": urljoin(url, anchor.get("href"))[:260]}
                    for anchor in anchors[:2000]
                    if PATTERN.search(str(anchor.get("href") or ""))
                ]
                row.update({
                    "anchors": len(anchors),
                    "recognized_job_links": len(jobs),
                    "samples": jobs[:10],
                    "title": soup.title.get_text(" ", strip=True)[:200]
                             if soup.title else "",
                    "body_visible": soup.get_text(" ", strip=True)[:400],
                    "iframe_sources": [
                        str(x.get("src") or "")[:250]
                        for x in soup.select("iframe")[:5]
                    ],
                })
            report[url] = row
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
