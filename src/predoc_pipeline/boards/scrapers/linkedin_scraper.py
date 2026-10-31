"""LinkedIn public (logged-out) job search.

Uses the public guest endpoint but this does not imply authorization to scrape.
LinkedIn restricts unauthorized automated collection; never bypass access
controls or increase traffic beyond the configured request ceiling. Guest job-search
results do NOT include ordinary LinkedIn posts or admissions announcements.

    GET https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
        ?keywords=predoc&location=European%20Union&f_TPR=r604800&start=0
    GET https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}

Option `backend: jobspy` switches to the python-jobspy library instead (pip install python-jobspy).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..http import FetchError
from ..models import JobPostSchema
from ..utils.dates import parse_iso_datetime, parse_posted
from ..utils.text import clean_ws, html_to_text
from .base import BaseScraper, register
from .linkedin_scheduler import QueryLedger

log = logging.getLogger(__name__)

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"
_ID = re.compile(r"(?:jobPosting:|/view/(?:[^/?]*-)?)(\d{6,})")


_MAX_REQUESTS = 120  # Shared configured budget across economics and Life Sciences.
_PAGE_FULL_AT = 10  # Full guest pages may have more matches.
_SLOT_SECONDS = 4 * 60 * 60


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
    soup = BeautifulSoup(html, "lxml")
    cards = []
    for card in soup.select("div.base-card, div.job-search-card, li > div[data-entity-urn]"):
        title_el = card.select_one(".base-search-card__title, h3")
        link_el = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
        urn = str(card.get("data-entity-urn") or "")
        href = str(link_el.get("href") or "") if link_el else ""
        m = _ID.search(urn) or _ID.search(href)
        if not title_el or not m:
            continue
        company_el = card.select_one(".base-search-card__subtitle, h4")
        loc_el = card.select_one(".job-search-card__location")
        time_el = card.select_one("time")
        cards.append({
            "id": m.group(1),
            "title": clean_ws(title_el.get_text(" ")),
            "company": clean_ws(company_el.get_text(" ")) if company_el else "",
            "location": clean_ws(loc_el.get_text(" ")) if loc_el else "",
            "datetime": time_el.get("datetime") if time_el else None,
            "posted_text": clean_ws(time_el.get_text(" ")) if time_el else None,
        })
    return cards


@register
class LinkedInScraper(BaseScraper):
    """Options: keywords (list), locations (list), f_TPR (default past week), max_pages, backend."""

    type_name = "linkedin"

    def urls(self) -> list[str]:
        return [SEARCH]

    def _scheduler_now(self) -> datetime:
        """Clock seam for offline scheduler tests."""
        return datetime.now(UTC)

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
        pairs = [(kw, loc) for kw in keywords for loc in locations]
        selected = ledger.plan(
            pairs, now=self._scheduler_now(),
            limit=query_budget, cooldown_hours=cooldown,
        )
        queue = deque(selected)
        self.search_diagnostics = {
            "backend": "guest_checkpointed",
            "total_pairs": len(set(pairs)), "plan_size": len(selected),
            "request_budget": request_budget, "time_budget_seconds": wall_seconds,
            "requests": 0, "completed_queries": 0, "failed_requests": 0,
            "access_limited": False, "pages_with_more_possible": 0,
            "time_budget_reached": False, "backpressure": False,
        }
        started = time.monotonic()
        failures = 0
        try:
            while queue and self.search_diagnostics["requests"] < request_budget:
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
                        self.http.get_text(url), timeout=remaining,
                    )
                except TimeoutError:
                    # No index advancement and no false full-coverage claim.
                    self.search_diagnostics["time_budget_reached"] = True
                    break
                except FetchError as exc:
                    failures += 1
                    ledger.fail(pair, now=self._scheduler_now(), status=exc.status)
                    self.search_diagnostics["failed_requests"] += 1
                    self.discovery_fetch_errors.append(
                        f"LinkedIn search HTTP {exc.status or 'fetch error'}"
                    )
                    if exc.status in {403, 429}:
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
                cards = parse_cards(html)
                if not cards and re.search(
                    r"captcha|sign[ -]?in.*(?:required|continue)", html, re.I,
                ):
                    ledger.fail(pair, now=self._scheduler_now(), status=403)
                    self.discovery_fetch_errors.append("LinkedIn access challenge")
                    self.search_diagnostics["access_limited"] = True
                    break
                if not cards and "data-entity-urn" in html:
                    ledger.fail(pair, now=self._scheduler_now())
                    self.discovery_parse_errors.append(
                        "LinkedIn listing cards could not be parsed",
                    )
                    continue
                try:
                    outcome = ledger.accept_page(
                        pair, cards, now=self._scheduler_now(),
                        max_pages=max_pages,
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
            # Local save is atomic; workflow stages this alongside the
            # publication journals, never in a separate post-processing commit.
            ledger.save(path)
        self.search_diagnostics.update(ledger.counts())
        self.search_diagnostics["unprocessed_selected"] = len(queue)
        return ledger.items(now=self._scheduler_now())

    async def fetch_raw_postings(self) -> list[Any]:
        if self.opt("backend", "guest") == "jobspy":
            self.search_diagnostics: dict[str, Any] = {
                "backend": "jobspy", "coverage": "unverified",
            }
            return await asyncio.to_thread(self._jobspy)
        if self.opt("checkpoint_path"):
            return await self._fetch_checkpointed()

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
                if exc.status in (403, 429):
                    # Stop; never rotate UA/proxy/account or bypass access controls.
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
            cards = parse_cards(html)
            if not cards and re.search(
                r"captcha|sign[ -]?in.*(?:required|continue)", html, re.I,
            ):
                self.search_diagnostics["access_limited"] = True
                self.discovery_fetch_errors.append("LinkedIn guest access challenge")
                break
            if not cards and "data-entity-urn" in html:
                self.discovery_parse_errors.append("Unparseable LinkedIn job cards")
            if depth == 0:
                self.search_diagnostics["completed_queries"] += 1
            for card in cards:
                card["_query"] = f"{kw} @ {loc}"
                raw.append(card)
            if len(cards) >= _PAGE_FULL_AT:
                self.search_diagnostics["pages_with_more_possible"] += 1
                if depth + 1 < max_pages:
                    # Breadth-first: first pages of selected searches before
                    # follow-up pages, subject to the same total request limit.
                    queue.append((kw, loc, start + len(cards), depth + 1))
        return raw

    def _jobspy(self) -> list[dict[str, Any]]:
        from jobspy import scrape_jobs  # optional dependency

        out = []
        for kw in self.opt("keywords", ["predoc"]):
            for loc in self.opt("locations", ["European Union"]):
                df = scrape_jobs(site_name=["linkedin"], search_term=kw, location=loc,
                                 results_wanted=int(self.opt("results_wanted", 50)), hours_old=168)
                for row in df.to_dict("records"):
                    m = _ID.search(str(row.get("job_url", "")))
                    if m:
                        out.append({"id": m.group(1), "title": row.get("title"), "company": row.get("company"),
                                    "location": row.get("location"), "datetime": str(row.get("date_posted") or ""),
                                    "description": row.get("description") or ""})
        return out

    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        posts: list[JobPostSchema] = []
        by_id: dict[str, JobPostSchema] = {}
        for card in raw_data:
            if not isinstance(card, dict):
                self.discovery_parse_errors.append("Malformed LinkedIn card")
                continue
            ident, title = card.get("id"), card.get("title")
            if (
                not isinstance(ident, str)
                or not ident.isascii() or not ident.isdigit() or len(ident) < 6
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
                },
            )
            by_id[ident] = post
            posts.append(post)
        return posts

    async def fetch_detail(self, post: JobPostSchema) -> str | None:
        job_id = post.extra.get("linkedin_id") or (_ID.search(post.url) or [None, None])[1]
        if not job_id:
            return None
        html = await self.http.get_text(DETAIL.format(job_id))
        soup = BeautifulSoup(html, "lxml")
        body = soup.select_one(".show-more-less-html__markup, .description__text")
        return clean_ws(body.get_text(" ")) if body else html_to_text(html, 20000)
