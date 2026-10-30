"""Read-only official DZNE d.vinci recruitment index investigation.

An accessible past vacancy is not a verified currently open doctoral post.
No job publication, career journal, authentication, or subscription access.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from predoc_pipeline.ingest.http import PoliteClient

URLS = (
    "https://jobs.dzne.de/en/jobs",
    "https://jobs.dzne.de/de/jobs",
    "https://jobs.dzne.de/sitemap.xml",
    "https://jobs.dzne.de/en/p/helmholz/jobs/101632/"
    "phd-candidate-fmx-in-ophthalmic-epidemiology-154720265",
)
UA = "Collegeum-LSSourceProbe/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
POSTING = re.compile(r"/(?:en|de)/(?:p/[^/]+/)?jobs/\d{4,12}/[^/?#]+")


def analyze(text: str, base: str) -> dict:
    soup = BeautifulSoup(text[:950000], "lxml")
    matched = []
    for anchor in soup.select("a[href]")[:8000]:
        href = urljoin(base, str(anchor.get("href") or ""))
        pieces = urlsplit(href)
        if pieces.scheme == "https" and pieces.hostname == "jobs.dzne.de":
            if POSTING.search(pieces.path):
                matched.append({
                    "url": href[:250],
                    "label": anchor.get_text(" ", strip=True)[:90],
                })
    scripts = []
    for script in soup.select("script[src]")[:80]:
        src = urljoin(base, str(script.get("src") or ""))
        scripts.append(src[:260])
    forms = [
        {"method": x.get("method"), "action": x.get("action")}
        for x in soup.select("form")[:5]
    ]
    content = soup.get_text(" ", strip=True)
    return {
        "individual_posting_links": len({row["url"] for row in matched}),
        "job_samples": matched[:12],
        "script_sources": scripts[-15:],
        "forms": forms,
        "jobposting_jsonld": sum(
            "JobPosting" in x.get_text()
            for x in soup.select('script[type="application/ld+json"]')
        ),
        "phd_mentions": content.lower().count("phd"),
        "application_closure_cue": any(
            t in content.lower() for t in (
                "applications closed", "bewerbung nicht mehr möglich",
                "application deadline passed",
            )
        ),
        "title": soup.title.get_text(" ", strip=True)[:200] if soup.title else "",
    }


def main() -> None:
    info = {}
    with PoliteClient(
        user_agent=UA, timeout=15, per_host_delay=2, respect_robots=True,
    ) as client:
        for url in URLS:
            response = client.get(url, use_cache=False)
            item = {
                "http_status": response.status,
                "error": response.error[:120],
                "bytes": len(response.content),
            }
            if response.ok:
                item.update(analyze(response.text, url))
                if url.endswith("sitemap.xml"):
                    item["xml_prefix"] = response.text[:350]
                    try:
                        root = ElementTree.fromstring(response.text)
                        locs = [
                            node.text.strip() for node in root.iter()
                            if node.tag.rsplit("}", 1)[-1] == "loc"
                            and isinstance(node.text, str) and node.text.strip()
                        ]
                    except ElementTree.ParseError:
                        locs = []
                    postings = [
                        x for x in locs
                        if urlsplit(x).hostname == "jobs.dzne.de"
                        and re.search(r"/(?:de|en)/(?:p/[^/]+/)?jobs/\d+/", urlsplit(x).path)
                    ]
                    phd = [
                        link for link in postings
                        if re.search(r"phd|doktorand|doctoral|promotion", link, re.I)
                    ]
                    item["sitemap_total_urls"] = len(locs)
                    item["sitemap_job_urls"] = len(postings)
                    item["sitemap_phd_slug_urls"] = len(phd)
                    item["doctoral_samples"] = phd[:16]
                    details = {}
                    for link in phd[:4]:
                        if not re.search(r"/(?:phd-|doctoral-|doktorand)", urlsplit(link).path):
                            continue
                        detail = client.get(link, use_cache=False)
                        record = {
                            "status": detail.status, "error": detail.error[:110],
                        }
                        if detail.ok:
                            soup = BeautifulSoup(detail.text[:300000], "lxml")
                            record["headings"] = [
                                tag.get_text(" ", strip=True)[:200]
                                for tag in soup.select("h1")[:3]
                            ]
                            record["text_prefix"] = soup.get_text(" ", strip=True)[:850]
                            record["application_links"] = [
                                urljoin(link, str(tag.get("href") or ""))[:190]
                                for tag in soup.select("a[href]")[:100]
                                if "apply" in tag.get_text(" ", strip=True).lower()
                                or "bewerben" in tag.get_text(" ", strip=True).lower()
                            ][:5]
                        details[link] = record
                    item["current_doctoral_details"] = details
            info[url] = item
    print(json.dumps(info, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
