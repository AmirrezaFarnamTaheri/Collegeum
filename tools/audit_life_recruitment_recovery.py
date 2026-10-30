"""Bounded read-only probe of disabled life-sciences recruitment candidates.

A successful HTTP response is not a source activation. This diagnostic reports
public employer vacancy anchors only; no subscriber state or posting writes.
"""
from __future__ import annotations

import json
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from predoc_pipeline.ingest.http import PoliteClient
from predoc_pipeline.ingest.life_sciences import load_life_sources

NAMES = {
    "life_dach_bern", "life_embl", "life_eth_bsse", "life_dkfz",
    "life_vienna_biocenter", "life_helsinki", "life_ista",
}
MAX_ANCHORS = 4000


def main() -> None:
    known = {
        item.name: item for item in load_life_sources("config/life_sciences.toml")
        if item.name in NAMES
    }
    assert set(known) == NAMES
    report = {}
    with PoliteClient(
        user_agent="Collegeum-LSSourceProbe/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)",
        timeout=16, per_host_delay=3, respect_robots=True,
    ) as client:
        for name in sorted(NAMES):
            config = known[name]
            base = config.opt("url")
            response = client.get(base, use_cache=False)
            row = {"url": base, "status": response.status, "error": response.error[:120]}
            if response.ok:
                soup = BeautifulSoup(response.text[:700000], "lxml")
                links = []
                for anchor in soup.select("a[href]")[:MAX_ANCHORS]:
                    href = urljoin(base, str(anchor.get("href") or ""))
                    parts = urlsplit(href)
                    label = anchor.get_text(" ", strip=True)
                    if (parts.scheme == "https" and parts.hostname and
                            any(word in (href + " " + label).lower()
                                for word in (
                                    "phd", "doctoral", "doctorand", "predoc",
                                    "vacanc", "job", "position",
                                ))):
                        links.append({"url": href[:240], "label": label[:90]})
                row["relevant_anchor_count"] = len(links)
                row["samples"] = links[:12]
                row["html_bytes"] = len(response.content)
            report[name] = row
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
