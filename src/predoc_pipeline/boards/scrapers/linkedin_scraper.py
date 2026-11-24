"""LinkedIn public (logged-out) job search.

Uses the public guest endpoint but this does not imply authorization to scrape.
LinkedIn restricts unauthorized automated collection; never bypass access
controls or increase traffic beyond the configured request ceiling. Guest job-search
results do NOT include ordinary LinkedIn posts or admissions announcements.

    GET https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
        ?keywords=predoc&location=European%20Union&f_TPR=r604800&start=0
    GET https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}

Only the bounded guest adapter is supported. A third-party backend cannot
replace its shared provider cooldown and checkpoint/request policy.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from ..http import FetchError
from ..models import JobPostSchema
from ..utils.dates import parse_iso_datetime, parse_posted
from .base import BaseScraper, register
from .linkedin_content import (
    job_id_from_url,
    parse_detail_page,
    parse_search_page,
    valid_job_id,
)
from .linkedin_scheduler import QueryLedger, _read_time

log = logging.getLogger(__name__)

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"


_MAX_REQUESTS = 120  # Combined configured search budget; detail enrichment has its own bounds.
_PAGE_FULL_AT = 10  # Full guest pages may have more matches.
_SLOT_SECONDS = 4 * 60 * 60


def _provider_access_denial(error: FetchError) -> bool:
    # The shared HTTP client can recognize an HTML gate before this adapter
    # receives its body. Retain the actual HTTP 200 while applying the same
    # provider cooldown as a gate recognized by the LinkedIn content parser.
    return error.status in {403, 429, 999} or (
        error.status == 200 and str(error) == "access_interstitial"
    )


def utc_search_slot(now: datetime) -> int:
    """Stable four-hour UTC rotation slot, independent of runner timezone."""
    if now.tzinfo is None:
        raise ValueError("UTC search slot requires timezone-aware clock")
    return int(now.astimezone(UTC).timestamp()) // _SLOT_SECONDS


def build_search_plan(
    keywords: list[str], locations: list[str], core_queries: list[tuple[str, str]],
    *, slot: int, query_budget: int,
) -> list[tuple[str, str]]:
    """Rotate a large portfolio within an explicitly bounded traffic budget.

    Every pair is scheduled in successive UTC slots, provided those runs
    execute. Planning is not proof of search visibility or vacancy status.
    """
    if not 1 <= query_budget <= _MAX_REQUESTS or slot < 0:
        raise ValueError("Invalid LinkedIn query budget or UTC slot")
    if not keywords or not locations:
        raise ValueError("LinkedIn portfolio requires keywords and locations")
    if any(not isinstance(x, str) or not x.strip() for x in keywords + locations):
        raise ValueError("Invalid LinkedIn search phrase or location")
    fixed = list(dict.fromkeys(core_queries))
    if len(fixed) >= query_budget:
        raise ValueError("Core queries must leave room for rotation")
    pool = list(dict.fromkeys(
        (kw, loc) for kw in keywords for loc in locations
        if (kw, loc) not in fixed
    ))
    if not pool:
        return fixed
    rotating_slots = min(query_budget - len(fixed), len(pool))
    start = (slot * rotating_slots) % len(pool)
    return fixed + [pool[(start + i) % len(pool)] for i in range(rotating_slots)]


def parse_cards(html: str) -> list[dict[str, Any]]:
    return parse_search_page(html).cards


@register
class LinkedInScraper(BaseScraper):
    """Options: keywords (list), locations (list), f_TPR (default past week), max_pages, backend."""

    type_name = "linkedin"

    def urls(self) -> list[str]:
        return [SEARCH]

    def _scheduler_now(self) -> datetime:
        """Clock seam for offline scheduler tests."""
        return datetime.now(UTC)

    def set_known_url(self, known: Callable[[str], bool]) -> None:
        """Attach the restored authoritative seen-journal lookup."""
        self._known_url = known

    def drop_filtered(self, post: JobPostSchema) -> None:
        """Retire a card conclusively excluded by the existing board filters."""
        ledger = getattr(self, "_checkpoint_ledger", None)
        if isinstance(ledger, QueryLedger):
            ident = post.extra.get("linkedin_id")
            if isinstance(ident, str):
                ledger.evict(ident)

    def mark_detail_attempt(self, post: JobPostSchema) -> None:
        """Durably prioritize candidates not yet checked for real deadlines."""
        ledger = getattr(self, "_checkpoint_ledger", None)
        if isinstance(ledger, QueryLedger):
            if self._access_is_blocked(now=self._scheduler_now()):
                return
            ident = post.extra.get("linkedin_id")
            if isinstance(ident, str):
                ledger.note_detail(ident, now=self._scheduler_now())

    def _provider_blocked_until(self, ledger: QueryLedger) -> datetime | None:
        """Read the other audience's restriction without modifying its ledger."""
        blocked = _read_time(ledger.state.get("access_blocked_until"))
        peer_path = self.opt("peer_checkpoint_path")
        peer_source = self.opt("peer_checkpoint_source")
        if peer_path is not None or peer_source is not None:
            if not isinstance(peer_path, str) or not peer_path.strip() or (
                not isinstance(peer_source, str) or not peer_source.strip()
            ):
                raise ValueError("Invalid LinkedIn peer checkpoint configuration")
            peer = QueryLedger.load(peer_path, peer_source)
            peer_block = _read_time(peer.state.get("access_blocked_until"))
            if peer_block is not None and (blocked is None or peer_block > blocked):
                blocked = peer_block
        return blocked

    def _access_is_blocked(self, *, now: datetime) -> bool:
        ledger = getattr(self, "_checkpoint_ledger", None)
        if ledger is None and self.opt("checkpoint_path"):
            ledger = QueryLedger.load(
                self.opt("checkpoint_path"), self.name,
                max_items=int(self.opt("max_replay_items", 3000)),
            )
            self._checkpoint_ledger = ledger
        block = getattr(self, "_session_access_blocked_until", None)
        if isinstance(ledger, QueryLedger):
            persisted = self._provider_blocked_until(ledger)
            if persisted is not None and (block is None or persisted > block):
                block = persisted
        return block is not None and now < block

    def _record_access_denial(self) -> None:
        """Stop this instance and persist the shared cooldown when configured."""
        until = self._scheduler_now() + timedelta(hours=48)
        self._session_access_blocked_until = until
        ledger = getattr(self, "_checkpoint_ledger", None)
        if isinstance(ledger, QueryLedger):
            previous = _read_time(ledger.state.get("access_blocked_until"))
            if previous is None or previous < until:
                ledger.state["access_blocked_until"] = until.isoformat()
            ledger.save(self.opt("checkpoint_path"))

    @property
    def intentionally_deferred(self) -> bool:
        """No eligible query was attempted; this is neither empty nor a fetch failure.

        Replayed cards remain available to the downstream filters. Never hide
        an actual request, malformed replay card or truncated cursor behind a
        provider-cooldown flag.
        """
        diagnostic = getattr(self, "search_diagnostics", None)
        return (
            isinstance(diagnostic, dict)
            and diagnostic.get("backend") in {"guest_checkpointed", "guest"}
            and diagnostic.get("requests") == 0
            and (
                diagnostic.get("provider_cooldown_active") is True
                or diagnostic.get("plan_size") == 0
            )
            and not any((
                self.discovery_fetch_errors,
                self.discovery_parse_errors,
                self.discovery_limits,
            ))
        )

    def flush_checkpoint(self) -> None:
        """Called after Life Sciences detail attempts, before final git commit."""
        ledger = getattr(self, "_checkpoint_ledger", None)
        if isinstance(ledger, QueryLedger):
            ledger.save(self.opt("checkpoint_path"))

    async def _fetch_checkpointed(self) -> list[Any]:
        """Time-boxed discovery; progress/candidates checkpoint in one ledger.

        This ledger and the output journals are staged in the SAME git commit.
        On a runner crash before commit, both revert to their previous state.
        Replay cards protect against downstream detail or publication deferral.
        """
        path = self.opt("checkpoint_path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("LinkedIn checkpoint path is required")
        keywords = list(self.opt("keywords", []))
        locations = list(self.opt("locations", []))
        query_budget = int(self.opt("query_budget", 24))
        request_budget = int(self.opt("request_budget", 30))
        wall_seconds = float(self.opt("time_budget_seconds", 180))
        max_pages = int(self.opt("max_pages", 12))
        cooldown = int(self.opt("cooldown_hours", 48))
        if (
            not 1 <= query_budget <= request_budget <= _MAX_REQUESTS
            or not 1 <= max_pages <= 50
            or not 1 <= wall_seconds <= 900
        ):
            raise ValueError("Invalid checkpointed LinkedIn request or runtime budget")
        ledger = QueryLedger.load(
            path, self.name, max_items=int(self.opt("max_replay_items", 3000)),
        )
        self._checkpoint_ledger = ledger
        seen_lookup = getattr(self, "_known_url", None)
        if callable(seen_lookup):
            ledger.prune_known(seen_lookup)
        pairs = [(kw, loc) for kw in keywords for loc in locations]
        core_config = self.opt("core_queries", [])
        if not isinstance(core_config, list):
            raise ValueError("LinkedIn core queries must be a list")
        core: list[tuple[str, str]] = []
        for item in core_config:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("keyword"), str)
                or not isinstance(item.get("location"), str)
                or not item["keyword"].strip() or not item["location"].strip()
            ):
                raise ValueError("Invalid LinkedIn core query")
            core.append((item["keyword"], item["location"]))
        provider_block = self._provider_blocked_until(ledger)
        provider_cooldown_active = (
            provider_block is not None and self._scheduler_now() < provider_block
        )
        # A pre-existing provider cooldown is a deliberate, policy-compliant
        # no-request interval, not another discovery limit or failed fetch.
        # The collector records it as skipped when no other error occurred.
        selected = ledger.plan(
            pairs, now=self._scheduler_now(),
            limit=query_budget, cooldown_hours=cooldown, core_pairs=core,
        )
        queue = deque([] if provider_cooldown_active else selected)
        self.search_diagnostics: dict[str, Any] = {
            "backend": "guest_checkpointed",
            "total_pairs": len(set(pairs)), "plan_size": len(selected),
            "request_budget": request_budget, "time_budget_seconds": wall_seconds,
            "requests": 0, "completed_queries": 0, "failed_requests": 0,
            "unverified_empty": 0,
            "repeated_pages": 0,
            "access_limited": False, "pages_with_more_possible": 0,
            "time_budget_reached": False, "backpressure": False,
            "provider_cooldown_active": provider_cooldown_active,
        }
        started = time.monotonic()
        failures = 0
        try:
            while queue and self.search_diagnostics["requests"] < request_budget:
                # A peer audience/detail task may have recorded denial since
                # planning. Recheck before taking another queued request.
                if self._access_is_blocked(now=self._scheduler_now()):
                    self.search_diagnostics["provider_cooldown_active"] = True
                    if self.search_diagnostics["requests"]:
                        self.discovery_limits.append("LinkedIn provider cooldown began during discovery")
                    break
                # Stop BEFORE downloading another page if all its candidates
                # could not be saved in the atomic replay checkpoint.
                if len(ledger.state["spool"]) >= ledger.max_items - 100:
                    self.search_diagnostics["backpressure"] = True
                    self.discovery_limits.append(
                        "LinkedIn replay backlog requires downstream processing",
                    )
                    break
                remaining = wall_seconds - (time.monotonic() - started)
                if remaining <= 0.5:
                    self.search_diagnostics["time_budget_reached"] = True
                    break
                pair = queue.popleft()
                cursor = ledger.request(pair, now=self._scheduler_now())
                params = {
                    "keywords": pair[0], "location": pair[1],
                    "f_TPR": f"r{cursor.window_seconds}", "start": cursor.offset,
                }
                url = f"{SEARCH}?{urlencode(params)}"
                self.search_diagnostics["requests"] += 1
                try:
                    html = await asyncio.wait_for(
                        self.http.get_text(url, stop_on_429=True), timeout=remaining,
                    )
                except TimeoutError:
                    # No index advancement and no false full-coverage claim.
                    self.search_diagnostics["time_budget_reached"] = True
                    break
                except FetchError as exc:
                    failures += 1
                    denied = _provider_access_denial(exc)
                    ledger.fail(pair, now=self._scheduler_now(), status=exc.status, access_denied=denied)
                    self.search_diagnostics["failed_requests"] += 1
                    self.discovery_fetch_errors.append(
                        f"LinkedIn search HTTP {exc.status or 'fetch error'}"
                    )
                    if denied:
                        self.search_diagnostics["access_limited"] = True
                        break
                    if failures >= 3:
                        break
                    continue
                except Exception as exc:  # noqa: BLE001 - retain collected cards
                    failures += 1
                    ledger.fail(pair, now=self._scheduler_now())
                    self.search_diagnostics["failed_requests"] += 1
                    self.discovery_fetch_errors.append(type(exc).__name__)
                    if failures >= 3:
                        break
                    continue
                failures = 0
                page = parse_search_page(html)
                cards = page.cards
                if page.access_challenge:
                    ledger.fail(pair, now=self._scheduler_now(), status=200, access_denied=True)
                    self.discovery_fetch_errors.append("LinkedIn access challenge")
                    self.search_diagnostics["access_limited"] = True
                    break
                if page.invalid_cards:
                    self.discovery_parse_errors.append(
                        "LinkedIn returned invalid or conflicting vacancy-card identities",
                    )
                if not cards:
                    # A blank body or interstitial is NOT verified zero results.
                    # Keep it distinct from confirmed malformed card markup.
                    ledger.defer_unverified_empty(pair, now=self._scheduler_now())
                    self.search_diagnostics["unverified_empty"] += 1
                    if "data-entity-urn" in html and not page.invalid_cards:
                        self.discovery_parse_errors.append(
                            "LinkedIn returned unparseable vacancy-card markup",
                        )
                    continue
                try:
                    outcome = ledger.accept_page(
                        pair, cards, now=self._scheduler_now(),
                        max_pages=max_pages, parse_complete=not page.invalid_cards,
                    )
                except ValueError:
                    ledger.fail(pair, now=self._scheduler_now())
                    self.discovery_parse_errors.append(
                        "LinkedIn page failed checkpoint validation",
                    )
                    continue
                if outcome == "backpressure":
                    self.search_diagnostics["backpressure"] = True
                    self.discovery_limits.append(
                        "LinkedIn candidate replay buffer at capacity",
                    )
                    break
                if outcome == "repeated_page":
                    self.search_diagnostics["repeated_pages"] += 1
                    self.discovery_parse_errors.append(
                        "LinkedIn repeated an accepted result page; query pagination deferred",
                    )
                if outcome in {"complete", "complete_with_gap"}:
                    self.search_diagnostics["completed_queries"] += 1
                elif outcome == "pending":
                    self.search_diagnostics["pages_with_more_possible"] += 1
                    queue.append(pair)
                elif outcome == "truncated":
                    self.search_diagnostics["pages_with_more_possible"] += 1
                    self.discovery_limits.append(
                        "LinkedIn query reached bounded pagination depth",
                    )
        finally:
            # Replay before persisting so expiration and cursor advancement
            # live in the same atomic state checkpoint. The workflow commits
            # this file alongside the output journals, not separately.
            batch_size = int(self.opt("emit_per_run", 350))
            raw = ledger.items(now=self._scheduler_now(), limit=batch_size)
            ledger.save(path)
        self.search_diagnostics.update(ledger.counts())
        self.search_diagnostics["pending_queries"] = self.search_diagnostics["incomplete_queries"]
        final_block = self._provider_blocked_until(ledger)
        self.search_diagnostics["access_blocked_until"] = (
            final_block.isoformat() if final_block is not None else None
        )
        self.search_diagnostics["unprocessed_selected"] = len(queue)
        return raw

    async def fetch_raw_postings(self) -> list[Any]:
        backend = self.opt("backend", "guest")
        if backend != "guest":
            self.search_diagnostics = {
                "backend": str(backend), "coverage": "unsupported", "requests": 0,
            }
            raise ValueError(
                "Unsupported LinkedIn backend: only the bounded guest adapter implements "
                "the shared provider cooldown and request policy",
            )
        if self.opt("checkpoint_path"):
            return await self._fetch_checkpointed()
        if self._access_is_blocked(now=self._scheduler_now()):
            self.search_diagnostics = {
                "backend": "guest", "requests": 0, "plan_size": 0,
                "provider_cooldown_active": True, "access_limited": False,
            }
            return []

        keywords = list(self.opt("keywords", ["predoc"]))
        locations = list(self.opt("locations", ["European Union"]))
        core_config = self.opt("core_queries", [])
        if not isinstance(core_config, list):
            raise ValueError("LinkedIn core_queries must be a list")
        core: list[tuple[str, str]] = []
        for entry in core_config:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("keyword"), str)
                or not isinstance(entry.get("location"), str)
            ):
                raise ValueError("Invalid LinkedIn core query")
            core.append((entry["keyword"], entry["location"]))
        query_budget = int(self.opt("query_budget", 24))
        request_budget = int(self.opt("request_budget", _MAX_REQUESTS))
        max_pages = int(self.opt("max_pages", 1))
        if not 1 <= request_budget <= _MAX_REQUESTS:
            raise ValueError("LinkedIn request budget must be 1..120")
        if not 1 <= max_pages <= 2:
            raise ValueError("LinkedIn max_pages must be 1..2")
        if query_budget > request_budget:
            raise ValueError("LinkedIn query budget exceeds request budget")
        slot = int(self.opt("query_slot", utc_search_slot(datetime.now(UTC))))
        plan = build_search_plan(
            keywords, locations, core, slot=slot, query_budget=query_budget,
        )
        self.search_diagnostics = {
            "backend": "guest", "rotation_slot": slot,
            "total_pairs": len(set((kw, loc) for kw in keywords for loc in locations)),
            "plan_size": len(plan), "query_budget": query_budget,
            "request_budget": request_budget, "max_pages": max_pages,
            "requests": 0, "completed_queries": 0,
            "failed_requests": 0, "access_limited": False,
            "pages_with_more_possible": 0,
        }
        queue = deque((kw, loc, 0, 0) for kw, loc in plan)
        raw: list[dict[str, Any]] = []
        failures_in_a_row = 0
        while queue and self.search_diagnostics["requests"] < request_budget:
            if self._access_is_blocked(now=self._scheduler_now()):
                self.search_diagnostics["provider_cooldown_active"] = True
                if self.search_diagnostics["requests"]:
                    self.discovery_limits.append("LinkedIn provider cooldown began during discovery")
                break
            kw, loc, start, depth = queue.popleft()
            params = {
                "keywords": kw, "location": loc,
                "f_TPR": self.opt("f_TPR", "r604800"), "start": start,
            }
            self.search_diagnostics["requests"] += 1
            try:
                html = await self.http.get_text(f"{SEARCH}?{urlencode(params)}")
            except FetchError as exc:
                self.search_diagnostics["failed_requests"] += 1
                self.discovery_fetch_errors.append(
                    f"LinkedIn search HTTP {exc.status or 'fetch failure'}"
                )
                if _provider_access_denial(exc):
                    # Stop; never rotate UA/proxy/account or bypass access controls.
                    self._record_access_denial()
                    self.search_diagnostics["access_limited"] = True
                    break
                failures_in_a_row += 1
                if failures_in_a_row >= 3:
                    break
                continue
            except Exception as exc:  # noqa: BLE001 - retain earlier observations
                self.search_diagnostics["failed_requests"] += 1
                self.discovery_fetch_errors.append(type(exc).__name__)
                failures_in_a_row += 1
                if failures_in_a_row >= 3:
                    break
                continue
            failures_in_a_row = 0
            page = parse_search_page(html)
            cards = page.cards
            if page.access_challenge:
                self._record_access_denial()
                self.search_diagnostics["access_limited"] = True
                self.discovery_fetch_errors.append("LinkedIn guest access challenge")
                break
            if page.invalid_cards or (not cards and "data-entity-urn" in html):
                self.discovery_parse_errors.append("Unparseable LinkedIn job cards")
            if cards and len(cards) < _PAGE_FULL_AT and not page.invalid_cards:
                self.search_diagnostics["completed_queries"] += 1
            for card in cards:
                card["_query"] = f"{kw} @ {loc}"
                raw.append(card)
            if len(cards) >= _PAGE_FULL_AT and not page.invalid_cards:
                self.search_diagnostics["pages_with_more_possible"] += 1
                if depth + 1 < max_pages:
                    # Breadth-first: first pages of selected searches before
                    # follow-up pages, subject to the same total request limit.
                    queue.append((kw, loc, start + len(cards), depth + 1))
                else:
                    self.discovery_limits.append("LinkedIn query reached bounded pagination depth")
        return raw

    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        posts: list[JobPostSchema] = []
        by_id: dict[str, JobPostSchema] = {}
        for card in raw_data:
            if not isinstance(card, dict):
                self.discovery_parse_errors.append("Malformed LinkedIn card")
                continue
            ident, title = card.get("id"), card.get("title")
            if (
                not valid_job_id(ident)
                or not isinstance(title, str) or not title.strip()
            ):
                self.discovery_parse_errors.append("Invalid LinkedIn job identity")
                continue
            query = card.get("_query") if isinstance(card.get("_query"), str) else ""
            extra_queries = card.get("_queries")
            matches = (
                [value for value in extra_queries
                 if isinstance(value, str) and value][:100]
                if isinstance(extra_queries, list)
                else [query] if query else []
            )
            if ident in by_id:
                queries = by_id[ident].extra["queries"]
                for value in matches:
                    if value not in queries:
                        queries.append(value)
                continue
            post = self.make(
                title=title, url=f"https://www.linkedin.com/jobs/view/{ident}",
                institution=card.get("company") or "",
                location=card.get("location") or None,
                date_posted=parse_iso_datetime(card.get("datetime"))
                or parse_posted(card.get("posted_text")),
                description_snippet=(card.get("description") or "")[:600],
                extra={
                    "linkedin_id": ident, "query": query or None,
                    "queries": matches,
                    "linkedin_detail_last_attempt_at": (
                        card.get("_detail_last_attempt_at")
                        if isinstance(card.get("_detail_last_attempt_at"), str) else None
                    ),
                },
            )
            by_id[ident] = post
            posts.append(post)
        return posts

    async def fetch_detail(self, post: JobPostSchema) -> str | None:
        link_id = job_id_from_url(post.url)
        job_id = post.extra.get("linkedin_id") or link_id
        if not valid_job_id(job_id) or link_id != job_id:
            post.extra["linkedin_detail_status"] = "invalid_job_identity"
            return None
        # Detail enrichment can run concurrently across sources. Serialize
        # this provider so queued requests observe an earlier access denial.
        if not hasattr(self, "_detail_lock"):
            self._detail_lock = asyncio.Lock()
        async with self._detail_lock:
            if self._access_is_blocked(now=self._scheduler_now()):
                post.extra["linkedin_detail_status"] = "provider_cooldown"
                return None
            try:
                html = await self.http.get_text(DETAIL.format(job_id), stop_on_429=True)
            except FetchError as exc:
                if _provider_access_denial(exc):
                    self._record_access_denial()
                raise
            detail = parse_detail_page(html, job_id)
            post.extra["linkedin_detail_status"] = detail.status
            if detail.status == "access_challenge":
                self._record_access_denial()
                raise FetchError("access_interstitial", status=200)
            return detail.text
