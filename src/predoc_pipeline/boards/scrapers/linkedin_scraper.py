"""LinkedIn public (logged-out) job search.

Uses the same guest endpoint that linkedin.com/jobs serves to anonymous visitors, so no account
is involved and nothing can get banned. Keep request volume low (min_interval >= 3s): the endpoint
answers 429 when hammered. LinkedIn's terms restrict automated access - use responsibly.

    GET https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
        ?keywords=predoc&location=European%20Union&f_TPR=r604800&start=0
    GET https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}

Option `backend: jobspy` switches to the python-jobspy library instead (pip install python-jobspy).
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..models import JobPostSchema
from ..utils.dates import parse_iso_datetime, parse_posted
from ..utils.text import clean_ws, html_to_text
from .base import BaseScraper, register

log = logging.getLogger(__name__)

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"
_ID = re.compile(r"(?:jobPosting:|/view/(?:[^/?]*-)?)(\d{6,})")


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

    async def fetch_raw_postings(self) -> list[Any]:
        if self.opt("backend", "guest") == "jobspy":
            return await asyncio.to_thread(self._jobspy)
        max_pages = int(self.opt("max_pages", 2))
        raw: list[dict[str, Any]] = []
        errors = consecutive = 0
        for kw in self.opt("keywords", ["predoc"]):
            for loc in self.opt("locations", ["European Union"]):
                if consecutive >= 3:  # blocked / rate-limited: stop hammering, keep what we have
                    break
                start = 0
                for _ in range(max_pages):
                    params = {"keywords": kw, "location": loc, "f_TPR": self.opt("f_TPR", "r604800"),
                              "start": start}
                    try:
                        html = await self.http.get_text(f"{SEARCH}?{urlencode(params)}")
                    except Exception as exc:  # noqa: BLE001 - keep other keyword/location combos going
                        errors += 1
                        consecutive += 1
                        log.warning("linkedin %r/%r failed: %s", kw, loc, exc)
                        break
                    consecutive = 0
                    cards = parse_cards(html)
                    for c in cards:
                        c["_query"] = f"{kw} @ {loc}"
                    raw.extend(cards)
                    if len(cards) < 10:
                        break
                    start += len(cards)
        if errors and not raw:
            raise RuntimeError(f"all {errors} LinkedIn requests failed (rate-limited?)")
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
        posts = []
        for c in raw_data:
            posts.append(self.make(
                title=c["title"], url=f"https://www.linkedin.com/jobs/view/{c['id']}",
                institution=c.get("company") or "", location=c.get("location") or None,
                date_posted=parse_iso_datetime(c.get("datetime")) or parse_posted(c.get("posted_text")),
                description_snippet=(c.get("description") or "")[:600],
                extra={"linkedin_id": c["id"], "query": c.get("_query")},
            ))
        return posts

    async def fetch_detail(self, post: JobPostSchema) -> str | None:
        job_id = post.extra.get("linkedin_id") or (_ID.search(post.url) or [None, None])[1]
        if not job_id:
            return None
        html = await self.http.get_text(DETAIL.format(job_id))
        soup = BeautifulSoup(html, "lxml")
        body = soup.select_one(".show-more-less-html__markup, .description__text")
        return clean_ws(body.get_text(" ")) if body else html_to_text(html, 20000)
