"""Read-only, robots-aware Helmholtz Munich PhD job-link verification.

The script does not enable a source, visit private endpoints, alter listing
history or send Telegram messages. A broad matching page is not verified.
"""
from __future__ import annotations

import json
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from predoc_pipeline.ingest.http import PoliteClient

CAREERS = "https://www.helmholtz-munich.de/en/career/jobs"
LAB = "https://www.helmholtz-munich.de/ife/job-opportunities"
PAGES = (CAREERS, LAB)
PROBE_USER_AGENT = (
    "Collegeum-LSSourceProbe/1.0 "
    "(+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
)


def summarize(html: str, base: str) -> dict:
    soup = BeautifulSoup(html[:900000], "lxml")
    links = []
    for anchor in soup.select("a[href]")[:5000]:
        href = urljoin(base, str(anchor.get("href") or ""))
        parts = urlsplit(href)
        title = anchor.get_text(" ", strip=True)
        if parts.scheme != "https" or not parts.hostname:
            continue
        if any(word in (title + " " + parts.path).lower()
               for word in ("phd", "doctoral", "doktor", "career", "job", "vacanc")):
            links.append({
                "url": href[:250], "title": title[:100],
                "host": (parts.hostname or "")[:100],
            })
    return {
        "anchor_candidates": len(links),
        "anchor_samples": links[:30],
        "jobposting_jsonld": sum(
            "JobPosting" in node.get_text()
            for node in soup.select('script[type="application/ld+json"]')
        ),
        "iframe_sources": [
            node.get("src", "")[:180] for node in soup.select("iframe[src]")[:8]
        ],
        "script_sources": [
            node.get("src", "")[:170] for node in soup.select("script[src]")[-12:]
        ],
        "phd_title_mentions": soup.get_text(" ", strip=True).lower().count("phd"),
    }


def main() -> None:
    results = {}
    with PoliteClient(
        user_agent=PROBE_USER_AGENT, timeout=16, per_host_delay=2,
        respect_robots=True,
    ) as http:
        for url in PAGES:
            response = http.get(url, use_cache=False)
            status = {"http_status": response.status, "error": response.error[:140]}
            if response.ok:
                status.update(summarize(response.text, url))
            results[url] = status
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
