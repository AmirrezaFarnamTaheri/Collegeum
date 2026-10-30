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
    "https://jobvision.ir/jobs/keyword/%D8%AF%D8%A7%D8%AF%D9%87",
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
                if url.endswith("sitemap.xml"):
                    row["preview"] = res.text[:600]
                soup = BeautifulSoup(res.text, "lxml")
                script = soup.select_one('script[type="application/json"]')
                if script:
                    row["data_script_id"] = str(script.get("id") or "")
                    row["data_script_size"] = len(script.get_text())
                    row["data_script_prefix"] = script.get_text()[:160]
                    try:
                        state = json.loads(script.get_text())
                        if isinstance(state, dict):
                            def shape(obj, depth=0):
                                if depth > 2:
                                    return type(obj).__name__
                                if isinstance(obj, dict):
                                    return {str(k)[:55]: shape(v, depth + 1)
                                            for k, v in list(obj.items())[:8]}
                                if isinstance(obj, list):
                                    return {"count": len(obj),
                                            "first": shape(obj[0], depth + 1)
                                            if obj else None}
                                return type(obj).__name__
                            row["data_script_keys"] = [
                                str(k)[:180] for k in list(state)[:20]
                            ]
                            row["data_script_job_shards"] = {
                                str(k)[:155]: shape(v)
                                for k, v in list(state.items())[:25]
                                if "job" in str(k).lower()
                            }
                    except ValueError:
                        row["data_script_parse"] = "invalid JSON"
                ld = soup.select_one('script[type="application/ld+json"]')
                if ld and "/jobs/" in url:
                    try:
                        data = json.loads(ld.get_text())
                        row["ld_keys"] = list(data)[:24] if isinstance(data, dict) else []
                    except ValueError:
                        row["ld_error"] = "invalid JSON-LD"
            rows[url] = row
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
