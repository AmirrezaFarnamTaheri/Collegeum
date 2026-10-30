"""Explore the *public* recruitment widget advertised by Helmholtz Munich.

Fail closed on robots/network errors. Inspect only publisher-declared script
attributes and public URLs; no hidden browser state, credentials or applications.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from predoc_pipeline.ingest.http import PoliteClient

URL = "https://www.helmholtz-munich.de/en/career/jobs"
UA = "Collegeum-LSSourceProbe/1.0 (+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
PAT = re.compile(r"b[-.]ite|jobs-api|jobposting|joblist|job-list|api-loader", re.I)
LINK = re.compile(r"https?://[A-Za-z0-9._:/?=&%-]+", re.I)


def inspect(html: str) -> dict:
    soup = BeautifulSoup(html[:1200000], "lxml")
    scripts = []
    for node in soup.select("script[src]"):
        val = node.get("src") or ""
        if PAT.search(val):
            scripts.append(urljoin(URL, val))
    candidate_tags = []
    for tag in soup.find_all(True):
        pairs = {
            k: " ".join(v) if isinstance(v, list) else str(v)
            for k, v in tag.attrs.items()
            if k not in {"class", "style", "id"} and PAT.search(k + "=" + str(v))
        }
        if pairs:
            candidate_tags.append({"tag": tag.name, "attrs": pairs})
    inline = []
    for node in soup.select("script:not([src])"):
        raw = node.string or node.get_text()
        for m in list(PAT.finditer(raw))[:8]:
            if m.start() > 0:
                inline.append(raw[max(0, m.start()-90):m.start()+200])
    return {
        "script_urls": scripts[:12],
        "matching_tags": candidate_tags[:12],
        "inline_snippets": inline[:12],
    }


def main() -> None:
    results = {}
    with PoliteClient(
        user_agent=UA, timeout=16, per_host_delay=2,
        respect_robots=True,
    ) as http:
        site = http.get(URL, use_cache=False)
        results["website"] = {"status": site.status, "error": site.error[:140]}
        if site.ok:
            details = inspect(site.text)
            results["website"].update(details)
            for script_url in details["script_urls"][:3]:
                host = urlsplit(script_url).hostname
                if host not in {"static.b-ite.com", "cs-assets.b-ite.com"}:
                    continue
                code = http.get(script_url, use_cache=False)
                record = {"status": code.status, "error": code.error[:140], "bytes": len(code.content)}
                if code.ok:
                    source = code.text
                    i = source.find("csListingPath")
                    record["loader_public_path_logic"] = source[max(0,i-120):i+1900]
                    record["urls"] = list(dict.fromkeys(LINK.findall(source)))[:24]
                    record["match_snippets"] = [
                        source[max(0, match.start()-80):match.start()+160]
                        for match in list(PAT.finditer(source))[:7]
                    ]
                results[script_url] = record
            customer = "helmholtz-zentrum-muenchen"
            resource = "main-listing-en"
            for suffix in ("", ".js", ".json"):
                candidate = (
                    "https://cs-assets.b-ite.com/" + customer +
                    "/jobs-api/" + resource + suffix
                )
                asset = http.get(candidate, use_cache=False)
                value = {
                    "status": asset.status,
                    "error": asset.error[:140],
                    "length": len(asset.content),
                }
                if asset.ok:
                    value["prefix"] = asset.text[:550]
                    value["script_urls"] = list(dict.fromkeys(
                        LINK.findall(asset.text)
                    ))[:10]
                results[candidate] = value
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
