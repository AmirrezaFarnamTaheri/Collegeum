"""Bounded, read-only audit of the opt-in Life Sciences PhD source registry.

This checks only explicitly enabled public landing pages; it never accesses
subscriber state. A 200 response with zero recognized vacancy links is NOT
evidence that the scraper still works. Fetches honor the existing polite
client's robots.txt checks and per-host pacing.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from predoc_pipeline.boards.config import load_board_sources
from predoc_pipeline.core.query_result_diversity import identical_nonempty_query_results
from predoc_pipeline.ingest.http import PoliteClient
from predoc_pipeline.ingest.life_sciences import load_life_sources

MAX_PROBE_SOURCES = 16
MAX_PARSE_CHARS = 650_000
MAX_QUERY_URLS = 4  # maximum number of configured URLs per enabled source
REGIONS = frozenset((
    "all", "core", "nordics", "dach", "benelux", "france_iberia",
    "central_south", "aggregator_topics", "eastern_balkans",
    "specialist_institutes", "doctoral_programmes",
))
PROBE_USER_AGENT = (
    "Collegeum-LSSourceProbe/1.0 "
    "(+https://github.com/AmirrezaFarnamTaheri/Collegeum)"
)


def candidate_job_urls(content: str, url: str, pattern: str) -> set[str]:
    """Recognize unique public HTTPS vacancy anchors, not script-only substrings."""
    soup = BeautifulSoup(content[:MAX_PARSE_CHARS], "lxml")
    matcher = re.compile(pattern, re.I)
    found: set[str] = set()
    for anchor in soup.select("a[href]")[:4000]:
        link = urljoin(url, str(anchor.get("href") or ""))
        try:
            parts = urlsplit(link)
        except ValueError:
            continue
        if (
            parts.scheme == "https" and parts.hostname
            and not parts.username and not parts.password
            and matcher.search(link)
        ):
            found.add(link)
    return found


def candidate_links(content: str, url: str, pattern: str) -> int:
    """Retain the count API used by existing fixtures and health checks."""
    return len(candidate_job_urls(content, url, pattern))

def search_page_evidence(content: str, url: str) -> dict[str, Any]:
    """Inspect visible search evidence and public form names, never input values.

    Only reading the provider's public form and an exact URL is permitted here.
    Form fields and keywords are diagnostic hints, not proof the server filtered.
    """
    query = parse_qs(urlsplit(url).query)
    keyword = ""
    for value in query.get("f[0]", []):
        if value.startswith("keywords:"):
            keyword = unquote(value.partition(":")[2]).casefold().strip()
            break
    # Public search forms also expose "keys" and "keywords". Reflection is
    # only a diagnostic hint; it never certifies server-side filtering.
    if not keyword:
        for name in ("keys", "keywords"):
            matches = query.get(name, [])
            if matches and 0 < len(matches[0]) <= 120:
                keyword = matches[0].casefold().strip()
                break
    soup = BeautifulSoup(content[:MAX_PARSE_CHARS], "lxml")
    visible = soup.get_text(" ", strip=True).casefold()
    match = re.search(r"\bsearch results?\s*\(\s*([0-9][0-9,]*)\s*\)", visible)
    search_names: set[str] = set()
    methods: set[str] = set()
    reflected = False
    for form in soup.select("form")[:20]:
        for field in form.select("input")[:80]:
            kind = str(field.get("type", "text")).casefold()
            name = str(field.get("name") or "")
            hint = " ".join(
                str(field.get(attr) or "") for attr in ("name", "placeholder", "aria-label")
            ).casefold()
            if kind not in {"text", "search"} or not (
                kind == "search" or "search" in hint or "keyword" in hint or "subject" in hint
            ):
                continue
            if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_:-]{0,63}", name):
                continue
            if any(secret in name.casefold() for secret in (
                "csrf", "token", "secret", "password"
            )):
                continue
            search_names.add(name)
            method = str(form.get("method") or "get").casefold()
            if method in {"get", "post"}:
                methods.add(method)
            if keyword and str(field.get("value") or "").casefold().strip() == keyword:
                reflected = True
    return {
        "keyword_in_visible_text": bool(keyword and keyword in visible),
        "declared_result_count": int(match.group(1).replace(",", "")) if match else None,
        "search_input_names": sorted(search_names)[:8],
        "search_form_methods": sorted(methods),
        "search_value_reflected": reflected,
    }


def feed_entries(content: str) -> int:
    """Count actual RSS/Atom entries, ignoring metadata and shell pages."""
    import feedparser

    result = feedparser.parse(content[:MAX_PARSE_CHARS])
    return len(result.entries)


def check_sources(
    client: Any, config: str | Path, *, region: str = "all",
    limit: int = MAX_PROBE_SOURCES, offset: int = 0,
    names: set[str] | None = None, detail_sample_limit: int = 0,
) -> dict[str, Any]:
    """Return bounded source, detail-access and exact observed-link overlap counts."""
    if not 1 <= limit <= MAX_PROBE_SOURCES:
        raise ValueError("limit must be between 1 and 16")
    if not 0 <= offset <= 256:
        raise ValueError("offset must be between 0 and 256")
    if region not in REGIONS:
        raise ValueError("unknown source region")
    if type(detail_sample_limit) is not int or not 0 <= detail_sample_limit <= 2:
        raise ValueError("detail_sample_limit must be between 0 and 2")
    sources = [s for s in load_life_sources(config) if s.enabled]
    if region == "core":
        core_ids = {
            s.name for s in load_board_sources(config) if s.enabled
        }
        sources = [s for s in sources if s.name in core_ids]
    elif region != "all":
        config_file = Path(config).parent / "life_sciences_sources" / f"{region}.toml"
        regional_ids = {s.name for s in load_board_sources(config_file)}
        sources = [s for s in sources if s.name in regional_ids]
    if names is not None:
        if (not isinstance(names, set) or not names or len(names) > 3
                or any(not isinstance(name, str) or not name for name in names)):
            raise ValueError("names must select one to three distinct source identifiers")
        if not names.issubset({source.name for source in sources}):
            raise ValueError("names must refer only to enabled sources in scope")
        if offset != 0 or limit < len(names):
            raise ValueError("named source selection may not silently skip a source")
        sources = [source for source in sources if source.name in names]

    report: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "region": region,
        "requested_names": sorted(names) if names else None,
        "enabled_in_scope": len(sources),
        "offset": offset, "limit": limit,
        "next_offset": (
            min(offset + limit, len(sources))
            if offset + limit < len(sources) else None
        ),
        "checked": 0,
        "sources": {},
    }
    source_candidate_urls: dict[str, set[str]] = {}
    for source in sources[offset:offset + limit]:
        if source.type in {"bite_jobs", "linkedin"}:
            # These adapters need provider-specific queries, not a static
            # landing page GET. Never probe LinkedIn as an HTML vacancy page
            # or confuse a missing static URL with failed source discovery.
            # Provider access policies still apply to any later adapter run.
            report["sources"][source.name] = {
                "status": "requires_adapter_probe",
                "adapter": source.type,
                "probe_workflow": str(source.opt("probe_workflow", "")),
                "http_status": 0,
                "vacancy_links": 0,
                "urls_total": 1, "urls_checked": 0, "endpoints": [],
            }
            report["checked"] += 1
            continue
        urls = source.opt("urls") or (
            [source.opt("url")] if source.opt("url") else []
        )
        # One source may expose multiple subject-search URLs. Checking only
        # urls[0] both misses vacancies and conceals failures on later pages.
        if not urls:
            report["sources"][source.name] = {
                "status": "missing_url", "http_status": 0, "vacancy_links": 0,
                "urls_total": 0, "urls_checked": 0, "endpoints": [],
            }
            report["checked"] += 1
            continue
        if len(urls) > MAX_QUERY_URLS:
            # Do not silently scan only a subset or make unbounded requests.
            report["sources"][source.name] = {
                "status": "too_many_urls", "http_status": 0, "vacancy_links": 0,
                "urls_total": len(urls), "urls_checked": 0, "endpoints": [],
            }
            report["checked"] += 1
            continue

        endpoints: list[dict[str, Any]] = []
        vacancy_urls: set[str] = set()
        rss_entry_count = 0
        query_observations: list[tuple[str, set[str]]] = []
        for url in urls:
            try:
                response = client.get(url, use_cache=False)
            except Exception as exc:  # noqa: BLE001 - keep other query pages observable
                endpoints.append({
                    "url": url, "status": "http_error", "http_status": 0,
                    "vacancy_links": 0, "failure_type": type(exc).__name__,
                })
                continue
            status = (
                "blocked_robots" if response.status == 999 else
                "http_error" if not response.ok else "ok"
            )
            matched = 0
            if response.ok:
                if source.type == "rss":
                    matched = feed_entries(response.text)
                    rss_entry_count += matched
                elif source.type == "link_scan":
                    try:
                        links = candidate_job_urls(
                            response.text, url, source.opt("link_pattern", "^$"),
                        )
                        matched = len(links)
                        vacancy_urls.update(links)
                        if source.opt("query_result_diversity_required") is True:
                            query_observations.append((url, links))
                    except re.error:
                        status = "invalid_pattern"
                else:
                    status = "unsupported_scraper"
                if status == "ok" and matched == 0:
                    status = "no_recognized_vacancy_links"
            entry = {
                "url": url, "status": status, "http_status": response.status,
                "vacancy_links": matched,
            }
            if (response.ok and source.type == "link_scan"
                    and source.opt("query_result_diversity_required") is True):
                entry.update(search_page_evidence(response.text, url))
            endpoints.append(entry)

        states = [item["status"] for item in endpoints]
        problems = {"blocked_robots", "http_error", "invalid_pattern", "unsupported_scraper"}
        if "ok" in states:
            status = "partial" if any(s in problems for s in states) else "ok"
        elif all(s == "no_recognized_vacancy_links" for s in states):
            status = "no_recognized_vacancy_links"
        elif all(s == states[0] for s in states):
            status = states[0]
        else:
            status = "partial"

        query_result_signal: str | None = None
        if source.opt("query_result_diversity_required") is True:
            if (len(query_observations) != len(urls)
                    or any(not links for _, links in query_observations)):
                query_result_signal = "indeterminate"
            elif identical_nonempty_query_results(query_observations):
                query_result_signal = "identical_nonempty"
                status = "partial"
            else:
                query_result_signal = "distinct_nonempty"
        report["sources"][source.name] = {
            "status": status,
            "http_status": endpoints[0]["http_status"],  # compatibility
            "vacancy_links": (
                len(vacancy_urls) if source.type == "link_scan"
                else rss_entry_count
            ),
            "urls_total": len(urls), "urls_checked": len(endpoints),
            "endpoints": endpoints,
        }
        if query_result_signal is not None:
            report["sources"][source.name]["query_result_signal"] = query_result_signal
        if source.type == "link_scan":
            # Count repeated index anchors by exact observed URL. These are
            # duplicate *search appearances*, not duplicated vacancies.
            source_candidate_urls[source.name] = set(vacancy_urls)
            report["sources"][source.name]["duplicate_link_appearances_across_query_pages"] = (
                sum(int(entry["vacancy_links"]) for entry in endpoints) - len(vacancy_urls)
            )
        if detail_sample_limit:
            # The same robots-aware, paced client inspects a bounded sample.
            # Never fetch a guessed ATS cross-origin link, a lookalike host or
            # an unvalidated link just because a broad regex matched a path.
            expected_host = urlsplit(urls[0]).hostname
            same_origin: list[str] = []
            if source.type == "link_scan":
                for candidate in sorted(vacancy_urls):
                    try:
                        parsed = urlsplit(candidate)
                        if (parsed.scheme == "https" and parsed.hostname == expected_host
                                and not parsed.username and not parsed.password):
                            same_origin.append(candidate)
                    except ValueError:
                        continue
            statuses: dict[str, int] = {}
            http_status_counts: dict[str, int] = {}
            for candidate in same_origin[:detail_sample_limit]:
                try:
                    response = client.get(candidate, use_cache=False)
                    http_status = response.status
                    detail_status = (
                        "blocked_robots" if http_status == 999
                        else "ok" if response.ok else "http_error"
                    )
                except Exception:  # noqa: BLE001 - per-detail failure remains observable
                    http_status = 0
                    detail_status = "http_error"
                statuses[detail_status] = statuses.get(detail_status, 0) + 1
                status_key = str(http_status)
                http_status_counts[status_key] = http_status_counts.get(status_key, 0) + 1
            report["sources"][source.name]["detail_probe"] = {
                "same_origin_candidates": len(same_origin),
                "sampled": min(len(same_origin), detail_sample_limit),
                "statuses": dict(sorted(statuses.items())),
                "http_status_counts": dict(sorted(http_status_counts.items())),
            }
        report["checked"] += 1
    names_checked = sorted(source_candidate_urls)
    shared: list[dict[str, Any]] = []
    for index, left in enumerate(names_checked):
        for right in names_checked[index + 1:]:
            count = len(source_candidate_urls[left] & source_candidate_urls[right])
            if count:
                shared.append({
                    "left": left, "right": right, "shared_link_urls": count,
                })
    all_observed: set[str] = set()
    for links in source_candidate_urls.values():
        all_observed.update(links)
    report["cross_source_overlap"] = {
        "source_pairs_examined": len(names_checked) * (len(names_checked) - 1) // 2,
        "observed_source_unique_link_total": sum(
            len(links) for links in source_candidate_urls.values()
        ),
        "distinct_observed_link_urls": len(all_observed),
        "pairwise_shared_link_counts": shared,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/life_sciences.toml")
    parser.add_argument("--region", default="all", choices=sorted(REGIONS))
    parser.add_argument("--limit", type=int, default=MAX_PROBE_SOURCES)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--names", nargs="+", help="One to three enabled source names")
    parser.add_argument("--detail-sample-limit", type=int, default=0,
                        help="Maximum same-origin vacancy details per source (0 to 2)")
    parser.add_argument(
        "--output", type=Path, default=Path("build/life-sciences-sources.json"),
    )
    args = parser.parse_args()
    with PoliteClient(
        user_agent=PROBE_USER_AGENT,
        timeout=15.0, per_host_delay=3.0, respect_robots=True,
    ) as client:
        report = check_sources(
            client, args.config, region=args.region, limit=args.limit,
            offset=args.offset, names=set(args.names) if args.names else None,
            detail_sample_limit=args.detail_sample_limit,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
