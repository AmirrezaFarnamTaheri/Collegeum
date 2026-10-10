"""Ingestion collectors and the gather orchestrator.

Every collector returns ``(items, SourceStats)`` and never raises into the
caller: one dead portal must not take the run down, but it must also be
*visible*, which is what the per-source stats are for. The reviewed
implementation swallowed exceptions into a log line and returned a flat list,
so a source that silently returned zero items for a month looked identical to a
quiet week.

Collector inventory, in order of how much they can be trusted:

``boards``   Job boards and university career sites (PREDOC.org, EJM, EJME,
             jobs.ac.uk, EURAXESS, Workday/Varbi portals, department pages,
             LinkedIn), via the scrapers in ``predoc_pipeline.boards``.
             Default on: these are where econ/business predocs are posted.
``feeds``    RSS/Atom that publishers deliberately syndicate. Default on.
``portals``  Schema.org ``JobPosting`` metadata embedded in career pages --
             published precisely so machines can read it. Default on.
``jobspy``   Commercial job boards. Default **off**; see COMPLIANCE.md.
``twitter``  Authenticated social search. Default **off**; see COMPLIANCE.md.

Optional collectors import their dependency inside the function, so the base
install stays small and a missing extra degrades to "source skipped" rather
than ``ImportError`` at startup.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit

from ..core.textproc import html_to_text, squish, truncate
from ..core.urls import canonicalize_url
from ..models import RawItem
from .http import PoliteClient
from .sources import Source

__all__ = ["SourceStats", "gather", "collect_feeds", "collect_portals", "COLLECTORS"]


@dataclass(slots=True)
class SourceStats:
    name: str
    items: int = 0
    fetched: int = 0
    unchanged: int = 0
    errors: int = 0
    messages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "items": self.items,
            "fetched": self.fetched,
            "unchanged": self.unchanged,
            "errors": self.errors,
            "messages": self.messages[:5],
        }


_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


# --------------------------------------------------------------------------
# Feeds
# --------------------------------------------------------------------------

def _feed_entry_text(entry: Any) -> tuple[str, str | None]:
    """Richest available body for an entry, plus the original HTML."""
    html = ""
    contents = getattr(entry, "content", None) or []
    if contents:
        html = max((c.get("value", "") for c in contents), key=len, default="")
    if not html:
        html = entry.get("summary") or entry.get("description") or ""
    return html_to_text(html), (html or None)


def collect_feeds(
    sources: list[Source], client: PoliteClient, *, max_items: int
) -> tuple[list[RawItem], list[SourceStats]]:
    """RSS/Atom ingestion via feedparser, fed from the polite client."""
    try:
        import feedparser
    except ImportError:  # pragma: no cover - feedparser is a base dependency
        return [], [SourceStats("feeds", errors=1, messages=["feedparser not installed"])]

    items: list[RawItem] = []
    stats: list[SourceStats] = []

    for source in sources:
        stat = SourceStats(source.name)
        result = client.get(source.url)
        stat.fetched = 1
        if result.skipped:
            stat.unchanged = 1
            stats.append(stat)
            continue
        if not result.ok:
            stat.errors = 1
            stat.messages.append(result.error or f"HTTP {result.status}")
            stats.append(stat)
            continue

        parsed = feedparser.parse(result.content or result.text.encode("utf-8"))
        if not parsed.version or (getattr(parsed, "bozo", False) and not parsed.entries):
            stat.errors = 1
            stat.messages.append(f"unparseable feed: {getattr(parsed, 'bozo_exception', '')}")
            stats.append(stat)
            continue

        if getattr(parsed, "bozo", False):
            stat.errors += 1
            stat.messages.append("malformed feed with recoverable entries")

        cap = source.max_items or max_items
        for entry in parsed.entries[:cap]:
            link = entry.get("link") or entry.get("id") or ""
            title = squish(entry.get("title", ""))
            if not link or not title:
                stat.errors += 1
                stat.messages.append("feed entry missing title or link")
                continue
            try:
                link = urljoin(getattr(result, "url", None) or source.url, link)
                parts = urlsplit(link)
                if parts.scheme not in {"http", "https"} or not parts.hostname:
                    raise ValueError("not a web link")
                _ = parts.port  # Reject malformed ports before emitting a vacancy.
            except ValueError:
                stat.errors += 1
                stat.messages.append("feed entry has invalid web link")
                continue
            text, html = _feed_entry_text(entry)
            body = f"{title}\n\n{text}".strip()
            items.append(
                RawItem(
                    source=f"feed:{source.name}",
                    source_url=canonicalize_url(link),
                    title=title,
                    text=body,
                    html=html,
                )
            )
            stat.items += 1
        stats.append(stat)

    return items, stats


# --------------------------------------------------------------------------
# Portals (Schema.org JobPosting)
# --------------------------------------------------------------------------

_JSONLD_BLOCK = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _iter_jobpostings(
    payload: Any, *, issues: list[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Walk arbitrarily nested JSON-LD looking for JobPosting nodes."""
    pending = [payload]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            types = node.get("@type")
            if isinstance(types, str):
                types = [types]
            elif types is None:
                types = []
            elif not isinstance(types, list):
                if issues is not None:
                    issues.append("invalid metadata type")
                types = []
            if any(isinstance(t, str) and t.lower() == "jobposting" for t in types):
                yield node
            pending.extend(reversed(list(node.values())))
        elif isinstance(node, list):
            pending.extend(reversed(node))


def _schema_name(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name")
    return squish(value) if isinstance(value, str) else ""


def _jobposting_items(
    html: str, page_url: str, source_name: str, *, issues: list[str] | None = None,
) -> list[RawItem]:
    """Parse JSON-LD independently and add optional Microdata extraction.

    extruct also reads Microdata and RDFa, which is worth having, but it is an
    optional extra: a JSON-LD-only fallback with the standard library covers
    the large majority of modern applicant-tracking systems and keeps the base
    install lean.
    """
    import json

    diagnostics = issues if issues is not None else []
    postings: list[dict[str, Any]] = []
    for block in _JSONLD_BLOCK.findall(html or ""):
        try:
            postings.extend(_iter_jobpostings(json.loads(block), issues=diagnostics))
        except (ValueError, TypeError, RecursionError):
            diagnostics.append("invalid JSON-LD block")
    try:
        import extruct
        from w3lib.html import get_base_url

        data = extruct.extract(
            html,
            base_url=get_base_url(html, page_url),
            syntaxes=["microdata"],
            uniform=True,
        )
        postings.extend(_iter_jobpostings(data.get("microdata", []), issues=diagnostics))
    except ImportError:
        pass  # JSON-LD parsing above works without the optional dependency.
    except Exception:
        diagnostics.append("microdata parser failed")

    items: list[RawItem] = []
    for posting in postings:
        raw_title = posting.get("title")
        title = squish(raw_title) if isinstance(raw_title, str) else ""
        if not title:
            diagnostics.append("JobPosting missing valid title")
            continue
        org = posting.get("hiringOrganization") or {}
        org_name = _schema_name(org)
        description = html_to_text(str(posting.get("description") or ""))
        location = posting.get("jobLocation") or {}
        locations = location if isinstance(location, list) else [location]
        places: list[str] = []
        for loc in locations:
            address = loc.get("address") if isinstance(loc, dict) else None
            if isinstance(address, dict):
                place = " ".join(filter(None, (
                    _schema_name(address.get(k))
                    for k in ("addressLocality", "addressRegion", "addressCountry")
                )))
            else:
                place = _schema_name(address)
            if place and place not in places:
                places.append(place)
        place = "; ".join(places)
        deadline = posting.get("validThrough") or ""
        raw_url = posting.get("url") or page_url
        try:
            if not isinstance(raw_url, str):
                raise ValueError("not a string")
            absolute = urljoin(page_url, raw_url)
            parts = urlsplit(absolute)
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                raise ValueError("not a web link")
            _ = parts.port
        except ValueError:
            diagnostics.append("JobPosting has invalid web link")
            continue
        url = canonicalize_url(absolute)
        body = "\n".join(
            part
            for part in (
                title,
                str(org_name or ""),
                place,
                f"Closing date: {deadline}" if deadline else "",
                "",
                description,
            )
            if part
        )
        items.append(
            RawItem(
                source=f"portal:{source_name}",
                source_url=url,
                title=title,
                text=body,
                apply_url_hint=url,
            )
        )
    return items


def _detail_links(html: str, page_url: str, pattern: str, limit: int) -> list[str]:
    """Candidate detail-page links from an index page."""
    from html import unescape
    from urllib.parse import urldefrag

    if not pattern or limit <= 0:
        return []
    matcher = re.compile(pattern, re.IGNORECASE)
    hrefs = _HREF_RE.findall(html or "")
    seen: set[str] = set()
    out: list[str] = []
    for href in hrefs:
        try:
            absolute = urljoin(page_url, unescape(href).strip())
            parts = urlsplit(absolute)
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                continue
            _ = parts.port
            if not parts.fragment.startswith(("/", "!/")):
                absolute = urldefrag(absolute)[0]
        except ValueError:
            continue
        if matcher.search(absolute) and absolute not in seen:
            seen.add(absolute)
            out.append(absolute)
        if len(out) >= limit:
            break
    return out


def _add_unique_postings(
    found: list[RawItem], seen: set[tuple[str, str]], candidates: list[RawItem],
) -> None:
    for candidate in candidates:
        key = (candidate.source_url, candidate.title.casefold())
        if key not in seen:
            seen.add(key)
            found.append(candidate)


def collect_portals(
    sources: list[Source], client: PoliteClient, *, max_items: int
) -> tuple[list[RawItem], list[SourceStats]]:
    """Read embedded JobPosting metadata from institutional career pages.

    Index pages rarely embed JobPosting themselves -- the detail pages do -- so
    a source may declare ``follow_links`` with a ``link_pattern`` and the
    collector will fetch a bounded number of detail pages behind it. The
    reviewed implementation pointed extruct at seven landing pages and would
    have found almost nothing.
    """
    items: list[RawItem] = []
    stats: list[SourceStats] = []

    for source in sources:
        stat = SourceStats(source.name)
        cap = source.max_items or max_items
        result = client.get(source.url)
        stat.fetched = 1
        if result.skipped:
            stat.unchanged = 1
            stats.append(stat)
            continue
        if not result.ok:
            stat.errors = 1
            stat.messages.append(result.error or f"HTTP {result.status}")
            stats.append(stat)
            continue

        parse_issues: list[str] = []
        found: list[RawItem] = []
        seen: set[tuple[str, str]] = set()

        _add_unique_postings(found, seen, _jobposting_items(
            result.text, result.url, source.name, issues=parse_issues,
        ))
        stat.errors += len(parse_issues)
        stat.messages.extend(parse_issues)

        if source.follow_links and len(found) < cap:
            for link in _detail_links(
                result.text, result.url, source.link_pattern, limit=cap
            ):
                detail = client.get(link)
                stat.fetched += 1
                if detail.skipped:
                    stat.unchanged += 1
                    continue
                if not detail.ok:
                    stat.errors += 1
                    continue
                parse_issues = []
                _add_unique_postings(found, seen, _jobposting_items(
                    detail.text, detail.url, source.name, issues=parse_issues,
                ))
                stat.errors += len(parse_issues)
                stat.messages.extend(parse_issues)
                if len(found) >= cap:
                    break

        found = found[:cap]
        items.extend(found)
        stat.items = len(found)
        if stat.items == 0 and stat.errors == 0:
            stat.messages.append("no JobPosting metadata found")
        stats.append(stat)

    return items, stats


# --------------------------------------------------------------------------
# Optional, terms-of-service sensitive collectors
# --------------------------------------------------------------------------

def collect_jobspy(settings: Any) -> tuple[list[RawItem], list[SourceStats]]:
    """Commercial job boards via python-jobspy. Opt-in; see COMPLIANCE.md."""
    stat = SourceStats("jobspy")
    try:
        from jobspy import scrape_jobs
    except ImportError:
        stat.messages.append("python-jobspy not installed (extra: boards)")
        return [], [stat]

    queries = (
        ("linkedin", "predoctoral research fellow", "Europe", None),
        ("linkedin", "pre-doctoral research assistant economics", "Europe", None),
        ("indeed", "predoctoral research assistant", "United Kingdom", "uk"),
        ("indeed", "research assistant economics", "Germany", "germany"),
    )
    per_query = max(5, settings.max_items_per_source // len(queries))
    items: list[RawItem] = []

    for site, term, location, country in queries:
        kwargs: dict[str, Any] = {
            "site_name": [site],
            "search_term": term,
            "location": location,
            "results_wanted": per_query,
            "hours_old": 72,
        }
        if country:
            kwargs["country_indeed"] = country
        if site == "linkedin":
            kwargs["linkedin_fetch_description"] = True
        try:
            frame = scrape_jobs(**kwargs)
        except Exception as exc:
            stat.errors += 1
            stat.messages.append(f"{site}/{term}: {exc}")
            continue
        stat.fetched += 1
        try:
            records = frame.to_dict("records")
        except AttributeError:  # pragma: no cover - shape change upstream
            records = list(frame or [])
        for record in records:
            url = record.get("job_url") or ""
            title = squish(str(record.get("title") or ""))
            if not url or not title:
                continue
            body = "\n".join(
                p
                for p in (
                    title,
                    squish(str(record.get("company") or "")),
                    squish(str(record.get("location") or "")),
                    "",
                    html_to_text(str(record.get("description") or "")),
                )
                if p
            )
            items.append(
                RawItem(
                    source=f"jobspy:{site}",
                    source_url=canonicalize_url(url),
                    title=title,
                    text=body,
                )
            )
            stat.items += 1
    return items, [stat]


def collect_x_api(
    settings: Any,
    client: Any | None = None,
) -> tuple[list[RawItem], list[SourceStats]]:
    """Query recent tweets via Official X API v2 (OAuth 2.0 Bearer Token)."""
    import os

    import httpx

    stat = SourceStats("x_api")
    bearer = getattr(settings, "x_bearer_token", "") or os.environ.get("X_BEARER_TOKEN", "")
    if not bearer:
        stat.messages.append("X_BEARER_TOKEN not set; source skipped")
        return [], [stat]

    queries = list(getattr(settings, "twitter_search_queries", []) or [
        (
            '(from:econ_RA OR "predoc" OR "pre-doc" OR "predoctoral") '
            "(economics OR finance) -is:retweet -is:reply"
        ),
        (
            '"research assistant" (economics OR finance) '
            '("hiring" OR "now accepting" OR "apply") -is:retweet -is:reply'
        ),
    ])
    accounts = list(getattr(settings, "twitter_search_accounts", []) or ["econ_RA", "predoc_org"])
    for acct in accounts:
        q = f"from:{acct} -is:retweet"
        if q not in queries:
            queries.append(q)

    max_items = getattr(settings, "max_items_per_source", 100)
    per_query = max(10, min(100, max_items // max(1, len(queries))))

    items: list[RawItem] = []
    seen_ids: set[str] = set()
    headers = {"Authorization": f"Bearer {bearer}"}
    endpoint = "https://api.x.com/2/tweets/search/recent"

    cm = client if client is not None else httpx.Client(timeout=20.0)
    try:
        for query in queries:
            params: dict[str, Any] = {
                "query": query,
                "max_results": per_query,
                "tweet.fields": "created_at,entities,author_id,text",
                "expansions": "author_id",
                "user.fields": "username,name",
            }
            try:
                resp = cm.get(endpoint, headers=headers, params=params)
            except Exception as exc:
                stat.errors += 1
                stat.messages.append(f"query failed ({query[:25]}...): {exc}")
                continue

            stat.fetched += 1
            if resp.status_code == 429:
                stat.errors += 1
                stat.messages.append("rate limited by X API (429)")
                break
            if resp.status_code != 200:
                stat.errors += 1
                stat.messages.append(f"X API status {resp.status_code}")
                continue

            payload = resp.json()
            users_by_id = {
                u["id"]: u.get("username", "user")
                for u in payload.get("includes", {}).get("users", [])
            }
            tweets = payload.get("data", [])
            for tweet in tweets:
                tid = tweet.get("id")
                if not tid or tid in seen_ids:
                    continue
                seen_ids.add(tid)
                text = tweet.get("text", "")
                if not text:
                    continue
                author = users_by_id.get(tweet.get("author_id"), "i")
                urls: list[str] = []
                for entity_url in tweet.get("entities", {}).get("urls", []):
                    expanded = entity_url.get("expanded_url") or entity_url.get("url")
                    if expanded and not (
                        expanded.startswith("https://twitter.com")
                        or expanded.startswith("https://x.com")
                    ):
                        urls.append(expanded)

                body = text
                if urls:
                    body += "\n\nLinks:\n" + "\n".join(urls)

                items.append(
                    RawItem(
                        source=f"twitter:@{author}",
                        source_url=f"https://x.com/{author}/status/{tid}",
                        title=truncate(squish(text), 100),
                        text=body,
                        hints={"author": author, "tweet_id": tid, "urls": urls},
                    )
                )
                stat.items += 1
    finally:
        if client is None:
            cm.close()

    return items, [stat]


def collect_xquik(
    settings: Any,
    client: Any | None = None,
) -> tuple[list[RawItem], list[SourceStats]]:
    """Query recent tweets via Xquik Platform REST API."""
    import os

    import httpx

    stat = SourceStats("xquik")
    api_key = getattr(settings, "xquik_api_key", "") or os.environ.get("XQUIK_API_KEY", "")
    if not api_key:
        stat.messages.append("XQUIK_API_KEY not set; source skipped")
        return [], [stat]

    queries = list(getattr(settings, "twitter_search_queries", []) or [
        '(from:econ_RA OR "predoc" OR "pre-doc") (economics OR finance)',
    ])
    max_items = getattr(settings, "max_items_per_source", 50)
    per_query = max(5, min(50, max_items // max(1, len(queries))))

    items: list[RawItem] = []
    seen_ids: set[str] = set()
    headers = {"x-api-key": api_key}
    endpoint = "https://xquik.com/api/v1/x/tweets/search"

    cm = client if client is not None else httpx.Client(timeout=20.0)
    try:
        for query in queries:
            try:
                resp = cm.get(
                    endpoint,
                    headers=headers,
                    params={"query": query, "limit": per_query},
                )
            except Exception as exc:
                stat.errors += 1
                stat.messages.append(f"xquik query failed ({query[:25]}...): {exc}")
                continue

            stat.fetched += 1
            if resp.status_code != 200:
                stat.errors += 1
                stat.messages.append(f"xquik status {resp.status_code}")
                continue

            payload = resp.json()
            if isinstance(payload, dict):
                tweets = payload.get("data", [])
            elif isinstance(payload, list):
                tweets = payload
            else:
                tweets = []
            for tweet in tweets:
                tid = tweet.get("id") or tweet.get("tweet_id")
                if not tid or tid in seen_ids:
                    continue
                seen_ids.add(tid)
                text = tweet.get("text") or tweet.get("full_text") or ""
                if not text:
                    continue
                author = tweet.get("username") or (tweet.get("user") or {}).get("username") or "i"
                items.append(
                    RawItem(
                        source=f"xquik:@{author}",
                        source_url=f"https://x.com/{author}/status/{tid}",
                        title=truncate(squish(text), 100),
                        text=text,
                        hints={"author": author, "tweet_id": tid},
                    )
                )
                stat.items += 1
    finally:
        if client is None:
            cm.close()

    return items, [stat]


def _collect_twscrape(settings: Any) -> tuple[list[RawItem], list[SourceStats]]:
    """Legacy scraper via twscrape. Opt-in; see COMPLIANCE.md."""
    import asyncio
    import os
    import tempfile
    from pathlib import Path

    stat = SourceStats("twscrape")
    blob = os.environ.get("TWSCRAPE_ACCOUNTS", "").strip()
    if not blob:
        stat.messages.append("TWSCRAPE_ACCOUNTS not set; source skipped")
        return [], [stat]
    try:
        from twscrape import API
        from twscrape import gather as tw_gather
    except ImportError:
        stat.messages.append("twscrape not installed (extra: social)")
        return [], [stat]

    queries = (
        '"predoctoral" (hiring OR vacancy OR "we are recruiting") -filter:replies',
        '"pre-doc" (economics OR finance) (hiring OR apply) -filter:replies',
        '"research assistant" economics (hiring OR "now accepting") -filter:replies',
    )
    per_query = max(5, settings.max_items_per_source // len(queries))

    async def run() -> list[RawItem]:
        out: list[RawItem] = []
        with tempfile.TemporaryDirectory() as tmp:
            session_db = str(Path(tmp) / "twscrape.db")
            api = API(session_db)
            for line in blob.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(":", 4)
                if len(parts) < 5:
                    stat.messages.append("malformed account line skipped")
                    continue
                try:
                    await api.pool.add_account(*parts[:4], cookies=parts[4])
                except Exception as exc:
                    stat.messages.append(f"add_account failed: {exc}")
            try:
                await api.pool.login_all()
            except Exception as exc:
                stat.messages.append(f"login: {exc}")
            for query in queries:
                try:
                    tweets = await tw_gather(api.search(query, limit=per_query))
                except Exception as exc:
                    stat.errors += 1
                    stat.messages.append(f"search failed: {exc}")
                    continue
                stat.fetched += 1
                for tweet in tweets:
                    text = getattr(tweet, "rawContent", "") or ""
                    if not text:
                        continue
                    username = getattr(getattr(tweet, "user", None), "username", "i")
                    out.append(
                        RawItem(
                            source="twscrape",
                            source_url=f"https://x.com/{username}/status/{tweet.id}",
                            title=truncate(squish(text), 100),
                            text=text,
                        )
                    )
                    stat.items += 1
        return out

    try:
        items = asyncio.run(run())
    except Exception as exc:
        stat.errors += 1
        stat.messages.append(f"twscrape: {exc}")
        return [], [stat]
    return items, [stat]


def collect_twitter(
    settings: Any,
    client: Any | None = None,
) -> tuple[list[RawItem], list[SourceStats]]:
    """Authenticated social search via Official X API v2, Xquik, or twscrape."""
    import os

    bearer = getattr(settings, "x_bearer_token", "") or os.environ.get("X_BEARER_TOKEN", "")
    if bearer:
        return collect_x_api(settings, client=client)

    xquik_key = getattr(settings, "xquik_api_key", "") or os.environ.get("XQUIK_API_KEY", "")
    if xquik_key:
        return collect_xquik(settings, client=client)

    if os.environ.get("TWSCRAPE_ACCOUNTS"):
        return _collect_twscrape(settings)

    stat = SourceStats("twitter")
    stat.messages.append(
        "No X/Twitter ingestion credentials found. Set X_BEARER_TOKEN (Official X API v2), "
        "XQUIK_API_KEY (Xquik platform), or TWSCRAPE_ACCOUNTS to enable social search."
    )
    return [], [stat]


COLLECTORS: dict[str, str] = {
    "boards": "job boards and university career sites (see [[board]] in sources.toml)",
    "feeds": "syndicated RSS/Atom feeds",
    "portals": "Schema.org JobPosting metadata on career pages",
    "jobspy": "commercial job boards (opt-in)",
    "twitter": "authenticated social search (opt-in)",
}


def gather(
    settings: Any,
    sources: list[Source],
    client: PoliteClient,
    *,
    only: set[str] | None = None,
    on_progress: Callable[[str, SourceStats], None] | None = None,
    prefs: Any | None = None,
    known: Callable[[str], bool] | None = None,
    board_transport: Any | None = None,
) -> tuple[list[RawItem], dict[str, Any]]:
    """Run every enabled collector. Returns items and per-source statistics.

    ``only`` names collectors ("boards", "feeds"...) or individual board
    sources ("cemfi", "linkedin"...). ``known(url)`` tells the boards collector
    which postings were already judged, so their pages are not re-read.
    """
    items: list[RawItem] = []
    stats: dict[str, Any] = {}

    def wanted(name: str) -> bool:
        return (only is None or name in only) and getattr(settings, f"enable_{name}", False)

    board_names = set(only or ()) - set(COLLECTORS)
    if getattr(settings, "enable_boards", False) and (only is None or "boards" in only
                                                      or board_names):
        from ..boards.collector import collect_boards
        from ..boards.config import load_preferences

        try:
            run = collect_boards(
                settings.sources_config,
                prefs or load_preferences(settings.preferences_config),
                known=known or (lambda _url: False),
                only=board_names or None,
                transport=board_transport,
            )
        except Exception as exc:  # pragma: no cover - collector-level guard
            stats["boards"] = {"items": 0, "errors": 1, "messages": [str(exc)[:200]]}
        else:
            items.extend(run.items)
            stats.update({f"board:{name}": data for name, data in run.stats.items()})
            stats["_boards"] = {"kind": "summary", "known": run.known,
                                "deferred": run.deferred, "rejected": run.rejected}

    if wanted("feeds"):
        feed_sources = [s for s in sources if s.kind == "feed" and s.enabled]
        got, per_source = collect_feeds(
            feed_sources, client, max_items=settings.max_items_per_source
        )
        items.extend(got)
        for stat in per_source:
            stats[f"feed:{stat.name}"] = stat.as_dict()
            if on_progress:
                on_progress("feeds", stat)

    if wanted("portals"):
        portal_sources = [s for s in sources if s.kind == "portal" and s.enabled]
        got, per_source = collect_portals(
            portal_sources, client, max_items=settings.max_items_per_source
        )
        items.extend(got)
        for stat in per_source:
            stats[f"portal:{stat.name}"] = stat.as_dict()
            if on_progress:
                on_progress("portals", stat)

    for name, collector in (("jobspy", collect_jobspy), ("twitter", collect_twitter)):
        if not wanted(name):
            continue
        try:
            got, per_source = collector(settings)
        except Exception as exc:  # pragma: no cover - collector-level guard
            stats[name] = {"items": 0, "errors": 1, "messages": [str(exc)[:200]]}
            continue
        items.extend(got)
        for stat in per_source:
            stats[stat.name] = stat.as_dict()
            if on_progress:
                on_progress(name, stat)

    return items, stats
