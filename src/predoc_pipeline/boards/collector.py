"""The ``boards`` collector: job boards -> ``RawItem`` for the main pipeline.

Order of work for one run (all async, a few sources at a time):

1. scrape every enabled ``[[board]]`` source;
2. cheap title-level rules (role wording, excluded titles, employer type, field,
   region, expiry) -- rejects here cost nothing and are simply re-judged tomorrow;
3. prioritize unseen postings before previously judged URLs;
4. read posting pages within the detail budget (following bit.ly & co.): deadline, PI, visa
   rules, "PhD required", filled/closed wording, dead links, real location;
5. emit a ``RawItem`` per new posting. Postings that failed a page-level rule are
   emitted too, with ``hints["reject"]`` set, so the pipeline records the verdict
   while allowing later changes to be reconsidered.

Postings over the page-reading budget are *not* emitted; the next run picks them up.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..models import RawItem
from .config import HttpConfig, Preferences, SourceConfig, load_board_sources
from .filter import RelevanceFilter, Verdict
from .heuristics import Enricher, check_still_open
from .http import HttpClient
from .models import JobPostSchema
from .scrapers import SCRAPERS, BaseScraper, SourceSkipped
from .scrapers.base import DiscoveryFetchError, DiscoveryParseError, generic_fetch_detail
from .utils.text import truncate

log = logging.getLogger(__name__)

__all__ = ["BoardRun", "SourceResult", "collect_boards", "check_links", "build_http"]


@dataclass
class SourceResult:
    scraper: BaseScraper
    posts: list[JobPostSchema] = field(default_factory=list)
    ok: bool = True
    skipped: bool = False
    error: str | None = None
    failure_stage: str | None = None
    seconds: float = 0.0
    n_relevant: int = 0
    n_new: int = 0

    def as_stats(self) -> dict[str, Any]:
        return {
            "kind": "board",
            "items": len(self.posts),
            "raw": len(self.posts),
            "relevant": self.n_relevant,
            "new": self.n_new,
            "fetched": 1 if self.ok and not self.skipped else 0,
            "errors": max(len(self.scraper.discovery_fetch_errors)
                          + len(self.scraper.discovery_parse_errors)
                          + len(self.scraper.discovery_limits), 0 if self.ok else 1),
            "ok": self.ok,
            "skipped": self.skipped,
            "may_be_empty": self.scraper.cfg.may_be_empty,
            "seconds": round(self.seconds, 1),
            "messages": [self.error] if self.error else [],
            "failure_stage": self.failure_stage,
        }


@dataclass
class BoardRun:
    items: list[RawItem] = field(default_factory=list)
    stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    rejected: dict[str, int] = field(default_factory=dict)
    known: int = 0
    deferred: int = 0

    def reject(self, reason: str | None) -> None:
        key = reason or "?"
        self.rejected[key] = self.rejected.get(key, 0) + 1


def build_http(cfg: HttpConfig, transport: httpx.AsyncBaseTransport | None = None) -> HttpClient:
    return HttpClient(
        timeout=cfg.timeout,
        max_retries=cfg.max_retries,
        backoff_base=cfg.backoff_base,
        default_min_interval=cfg.default_min_interval,
        user_agents=cfg.user_agents or None,
        transport=transport,
    )


def select_sources(
    sources: list[SourceConfig], only: set[str] | None = None
) -> list[SourceConfig]:
    """Enabled sources, or the ones named in ``only`` (by name, group or type).

    ``only={"boards"}`` means every enabled board. Naming a disabled source
    explicitly still runs it (useful for testing a fix).
    """
    if not only or "boards" in only:
        return [s for s in sources if s.enabled]
    return [
        s for s in sources
        if s.name in only or (s.enabled and (s.group in only or s.type in only))
    ]


async def _scrape_all(
    scrapers: list[BaseScraper], max_concurrent: int, timeout: float
) -> list[SourceResult]:
    if max_concurrent <= 0:
        raise ValueError("source concurrency must be positive")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("source timeout must be finite and positive")
    sem = asyncio.Semaphore(max_concurrent)

    async def one(s: BaseScraper) -> SourceResult:
        async with sem:
            t0 = time.monotonic()
            res = SourceResult(s)
            try:
                res.posts, _ = await asyncio.wait_for(s.run(), timeout=timeout)
                if s.discovery_fetch_errors:
                    res.ok = False
                    res.failure_stage = "fetch"
                    res.error = f"{len(s.discovery_fetch_errors)} discovery endpoint(s) failed"
                if s.discovery_parse_errors:
                    res.ok = False
                    res.failure_stage = "fetch/parse" if s.discovery_fetch_errors else "parse"
                    note = f"{len(s.discovery_parse_errors)} payload(s) parsed incompletely"
                    res.error = f"{res.error}; {note}" if res.error else note
                if s.discovery_limits:
                    res.ok = False
                    res.failure_stage = (
                        f"{res.failure_stage}/limit" if res.failure_stage else "limit"
                    )
                    note = f"{len(s.discovery_limits)} discovery limit(s) reached"
                    res.error = f"{res.error}; {note}" if res.error else note
            except TimeoutError:
                res.ok, res.error = False, f"timed out after {timeout:.0f}s"
                res.failure_stage = "timeout"
            except SourceSkipped as exc:
                res.skipped, res.error = True, f"skipped: {exc}"
            except Exception as exc:  # noqa: BLE001 - one broken source must not sink the run
                res.ok, res.error = False, f"{type(exc).__name__}: {exc}"[:500]
                res.failure_stage = (
                    "fetch" if isinstance(exc, DiscoveryFetchError)
                    else "parse" if isinstance(exc, DiscoveryParseError) else "discovery"
                )
                log.warning("board %s failed: %s", s.name, res.error)
            res.seconds = time.monotonic() - t0
            log.info("board %-28s %4d postings %s", s.name, len(res.posts),
                     "(skipped)" if res.skipped else "" if res.ok else "FAILED")
            return res

    return list(await asyncio.gather(*(one(s) for s in scrapers)))


def _structured_text(post: JobPostSchema) -> str:
    """What the list page told us, as labelled lines (used when no page text exists)."""
    lines = [
        ("Institution", post.institution),
        ("Department", post.department),
        ("Location", post.location or post.country),
        ("Fields", post.fields_of_research),
        ("Deadline", post.deadline.isoformat() if post.deadline else post.deadline_text),
        ("Supervisor", post.pi_name),
    ]
    head = "\n".join(f"{k}: {v}" for k, v in lines if v)
    return "\n".join(x for x in (head, post.description_snippet) if x)


def to_raw_item(post: JobPostSchema, verdict: Verdict, *, detail: str = "",
                reject: str | None = None, enriched: bool = False) -> RawItem:
    final_url = post.extra.get("final_url") or ""
    apply_hint = final_url if final_url and final_url != post.url else None
    text = detail or _structured_text(post) or post.title
    hints: dict[str, Any] = {
        "board": True,
        "institution": post.institution or None,
        "department": post.department,
        "country": post.country,
        "region": post.region,
        "location": post.location,
        "fields": post.fields_of_research,
        "deadline": post.deadline.isoformat() if post.deadline else None,
        "deadline_text": post.deadline_text,
        "pi": post.pi_name,
        "visa_note": post.visa_note,
        "field_implied": post.field_implied,
        "employer_required": bool(post.extra.get("employer_required")),
        "strong": verdict.strong,
        "score": verdict.score,
        "summary": truncate(post.description_snippet or "", 600),
        "final_url": final_url or None,
        "enriched": enriched,
        "reject": reject,
    }
    return RawItem(
        source=post.source,
        source_url=post.url,
        title=post.title,
        text=text[:12000],
        apply_url_hint=apply_hint,
        hints={k: v for k, v in hints.items() if v not in (None, "")},
    )


async def _collect(
    sources: list[SourceConfig],
    prefs: Preferences,
    known: Callable[[str], bool],
    http: HttpClient,
) -> BoardRun:
    out = BoardRun()
    flt = RelevanceFilter(prefs.filters)
    scrapers: list[BaseScraper] = []
    for cfg in sources:
        if cfg.type not in SCRAPERS:
            out.stats[cfg.name] = {"kind": "board", "ok": False, "items": 0, "errors": 1,
                                   "messages": [f"unknown board type {cfg.type!r}"]}
            continue
        scrapers.append(SCRAPERS[cfg.type](cfg, http))
    if not scrapers:
        return out
    results = await _scrape_all(scrapers, prefs.http.max_concurrent_sources,
                                prefs.http.source_timeout)

    # ---- 1. title-level rules + region + in-run duplicates -------------------------
    candidates: dict[str, tuple[SourceResult, JobPostSchema, Verdict]] = {}
    by_fingerprint: dict[str, JobPostSchema] = {}
    by_url: dict[str, str] = {}
    for res in results:
        for post in res.posts:
            verdict = flt.evaluate(post)
            if not verdict.keep:
                out.reject(verdict.reason)
                continue
            flt.assign_region(post)
            ok, why = flt.region_ok(post)
            if not ok:
                out.reject(why)
                continue
            res.n_relevant += 1
            twin = by_fingerprint.get(post.fingerprint)
            if twin and twin.source != post.source:
                out.reject("duplicate-in-run")  # same job on two boards today
                continue
            other_id = by_url.get(post.url)
            if other_id and other_id != post.job_id:
                if verdict.score <= candidates[other_id][2].score:
                    out.reject("duplicate-in-run")
                    continue
                del candidates[other_id]
            by_fingerprint.setdefault(post.fingerprint, post)
            by_url[post.url] = post.job_id
            prev = candidates.get(post.job_id)
            if not prev or verdict.score > prev[2].score:
                candidates[post.job_id] = (res, post, verdict)

    # ---- 2. unseen postings first, then refresh known URLs within the same budget --
    new_items = []
    known_items = []
    for item in candidates.values():
        if known(item[1].url):
            out.known += 1
            known_items.append(item)
        else:
            new_items.append(item)
    new_items.sort(key=lambda v: -v[2].score)
    known_items.sort(key=lambda v: -v[2].score)
    new_items.extend(known_items)

    # ---- 3. read each new posting's page -------------------------------------------
    enrich = prefs.enrich
    to_enrich = [(res.scraper, post) for res, post, _ in new_items][: enrich.max_details_per_run]
    enriched_ids = await Enricher(enrich).enrich_many(to_enrich)
    attempted = {p.job_id for _, p in to_enrich}

    # ---- 4. page-level rules --------------------------------------------------------
    for res, post, verdict in new_items:
        pid = post.job_id
        if enrich.fetch_details and pid not in attempted:
            out.deferred += 1  # over today's budget: the next run picks it up
            continue
        reason: str | None = None
        detail = post.extra.pop("detail_text", "")
        strong = verdict.strong
        if post.extra.get("closed"):
            reason = "filled-or-closed"
        elif detail and any(rx.search(detail[:2000]) for rx in flt.emp_banned):
            reason = "excluded-employer"  # e.g. "J-PAL Europe" named only in the ad text
        elif pid in enriched_ids and detail:
            field_v = flt.field_verdict_long(detail)
            if field_v == "unwanted":
                reason = "wrong-field-detail"
            elif verdict.needs_field_check and field_v != "wanted":
                reason = "no-field-in-detail"
        elif verdict.needs_field_check and not strong:
            out.deferred += 1  # page unreachable today and field unknown: retry tomorrow
            continue
        if not reason and prefs.filters.exclude_phd_positions and post.extra.get("phd_required") and not strong:
            reason = "requires-phd"
        if not reason:
            ok, why = flt.region_ok(post)  # the page may have revealed the location
            if not ok:
                reason = why
        if not reason:
            again = flt.evaluate(post)  # the page may have revealed a past deadline
            if not again.keep and again.reason in ("expired", "stale"):
                reason = again.reason
        if reason:
            out.reject(reason)
        else:
            res.n_new += 1
        if post.extra.get("closed"):
            post.extra["closed_reason"] = post.extra["closed"]
        out.items.append(
            to_raw_item(post, verdict, detail=detail, reject=reason, enriched=pid in enriched_ids)
        )

    for res in results:
        out.stats[res.scraper.name] = res.as_stats()
    return out


def collect_boards(
    sources_config: str,
    prefs: Preferences,
    *,
    known: Callable[[str], bool] = lambda _url: False,
    only: set[str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BoardRun:
    """Synchronous entry point used by ``ingest.collectors.gather``."""
    sources = select_sources(load_board_sources(sources_config), only)
    if not sources:
        return BoardRun()

    async def go() -> BoardRun:
        async with build_http(prefs.http, transport) as http:
            return await _collect(sources, prefs, known, http)

    return asyncio.run(go())


def verify_boards(
    sources_config: str, prefs: Preferences,
    *, transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, dict[str, Any]]:
    """Probe discovery through production adapters without gating or enrichment."""
    sources = select_sources(load_board_sources(sources_config))

    async def go() -> dict[str, dict[str, Any]]:
        stats: dict[str, dict[str, Any]] = {}
        async with build_http(prefs.http, transport) as http:
            scrapers = []
            for cfg in sources:
                if cfg.type not in SCRAPERS:
                    stats[cfg.name] = {"ok": False, "errors": 1, "items": 0,
                                       "messages": [f"unknown board type {cfg.type!r}"]}
                else:
                    scrapers.append(SCRAPERS[cfg.type](cfg, http))
            results = await _scrape_all(
                scrapers, prefs.http.max_concurrent_sources, prefs.http.source_timeout,
            )
            stats.update({result.scraper.name: result.as_stats() for result in results})
        return stats

    return asyncio.run(go())


# ------------------------------------------------------------------------------------
# Is it still open?  (before sending, and every few days after)
# ------------------------------------------------------------------------------------

class _Opener:
    """Opens any link the generic way: follows redirects, reads Workday via its API."""

    def __init__(self, http: HttpClient):
        self.http = http

    async def fetch_detail(self, post: JobPostSchema) -> str | None:
        return await generic_fetch_detail(self.http, post)


def check_links(
    links: dict[Any, tuple[Any, ...]],
    http_cfg: HttpConfig,
    *,
    concurrency: int = 6,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[Any, str | None]:
    """``{key: (title, url[, deadline])}`` -> ``{key: reason it is filled/closed, or None}``.

    Passing the known deadline (a ``date``) stops a dated line such as "review
    of applications begins 15 Sep" from being mistaken for a passed deadline.

    A link that answers 404/410 (bit.ly does this when a predoc is filled), a page
    saying "this position has been filled", a Workday posting that no longer
    accepts applications, or a start date long gone all count as closed. A site
    that is merely unreachable does *not*: unknown is not closed.
    """
    if concurrency <= 0:
        raise ValueError("link-check concurrency must be positive")
    if not links:
        return {}

    async def go() -> dict[Any, str | None]:
        out: dict[Any, str | None] = {}
        sem = asyncio.Semaphore(concurrency)
        async with build_http(http_cfg, transport) as http:
            opener = _Opener(http)

            async def one(key: Any, title: str, url: str, deadline: Any = None) -> None:
                async with sem:
                    post = JobPostSchema(title=title or "position", url=url, source="recheck",
                                         deadline=deadline)
                    try:
                        out[key] = await check_still_open(opener, post)
                    except Exception as exc:  # noqa: BLE001 - never fail a run over a recheck
                        log.info("recheck failed for %s: %s", url, exc)
                        out[key] = None

            await asyncio.gather(*(one(k, *value) for k, value in links.items()))
        return out

    return asyncio.run(go())
