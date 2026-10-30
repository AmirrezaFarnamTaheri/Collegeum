"""Read-only verification of public Jobvision index, sitemap and vacancy markup.

No authentication, undocumented API or publication access. Policy checks are
performed before each request using the shared fail-closed PoliteClient.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from predoc_pipeline.ingest.http import PoliteClient

URLS = (
    "https://jobvision.ir/robots.txt",
    "https://jobvision.ir/jobs",
    "https://jobvision.ir/sitemap.xml",
    "https://jobvision.ir/jobs/1454248",
)
JOB = re.compile(r"^/jobs/[1-9]\d{3,10}(?:/[^/?#]+)?/?$")


def inspect(html: str, base: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    for tag in soup.select("a[href], loc")[:30000]:
        link = str(tag.get("href") or tag.get_text(" ", strip=True))
        parts = urlsplit(link)
        if parts.hostname not in (None, "jobvision.ir", "www.jobvision.ir"):
            continue
        if JOB.fullmatch(parts.path):
            jobs.append(parts.path)
    script_types = {}
    for tag in soup.select("script[type]"):
        key = str(tag.get("type"))
        script_types[key] = script_types.get(key, 0) + 1
    return {
        "job_paths": len(set(jobs)),
        "job_samples": list(dict.fromkeys(jobs))[:5],
        "title": str(soup.title.get_text(" ", strip=True))[:180] if soup.title else "",
        "h1": [x.get_text(" ", strip=True)[:100] for x in soup.select("h1")[:2]],
        "script_types": script_types,
        "has_jobposting_jsonld": "JobPosting" in html,
        "has_sitemapindex": "<sitemapindex" in html.lower(),
        "has_urlset": "<urlset" in html.lower(),
        "has_no_jobs_message": "فرصت شغلی برای جستجوی شما پیدا نشد" in html,
    }


def main() -> None:
    rows = {}
    with PoliteClient(
        user_agent="CollegeumCareerProbe/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)",
        timeout=18, per_host_delay=2, respect_robots=True,
    ) as client:
        for url in URLS:
            res = client.get(url, use_cache=False)
            row = {"status": res.status, "error": res.error[:140], "bytes": len(res.content)}
            if res.ok:
                row.update(inspect(res.text, url))
            rows[url] = row
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
