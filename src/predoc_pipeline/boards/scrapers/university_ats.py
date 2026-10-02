"""University ATS adapters.

* Workday (UBC, McGill, ...): the public career sites are backed by an unauthenticated JSON API
      POST https://{host}/wday/cxs/{tenant}/{site}/jobs  {"searchText", "limit" (<=20!), "offset", "appliedFacets"}
      GET  https://{host}/wday/cxs/{tenant}/{site}{externalPath}   -> full posting
* Varbi (Stockholm University, SSE, many Nordic employers) and Stonefish/engage (LSE) render plain
  HTML tables -> handled by LinkScanScraper with a preset link pattern (see VarbiScraper).
* JS-only boards -> `render_page()` (Playwright), used by LinkScanScraper when `render: true`.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlsplit

from ..models import JobPostSchema
from ..utils.dates import parse_iso_datetime, parse_posted, today
from ..utils.text import clean_ws, html_to_text
from .base import BaseScraper, register
from .link_scan import LinkScanScraper

log = logging.getLogger(__name__)

_LOCALE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")


def parse_workday_url(url: str) -> tuple[str, str, str, str | None]:
    """https://ubc.wd10.myworkdayjobs.com/en-US/ubcstaffjobs -> (host, tenant, site, locale)."""
    parts = urlsplit(url)
    host = parts.netloc
    tenant = host.split(".")[0]
    segs = [s for s in parts.path.split("/") if s]
    locale = None
    if segs and _LOCALE.match(segs[0]):
        locale = segs.pop(0)
    if not segs:
        raise ValueError(f"Cannot find Workday site name in {url}")
    return host, tenant, segs[0], locale


@register
class WorkdayScraper(BaseScraper):
    """Options: url (career site), search_terms (list), max_pages (per term, 20 jobs/page)."""

    type_name = "workday"
    PAGE = 20  # Workday silently returns [] for limit > 20

    async def fetch_raw_postings(self) -> list[Any]:
        host, tenant, site, _ = parse_workday_url(self.opt("url"))
        api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        max_pages = int(self.opt("max_pages", 3))
        raw: list[dict] = []
        for term in self.opt("search_terms", [""]):
            for page in range(max_pages):
                payload = {"appliedFacets": {}, "limit": self.PAGE, "offset": page * self.PAGE, "searchText": term}
                data = await self.http.post_json(api, payload)
                batch = data.get("jobPostings", []) or []
                raw.extend(batch)
                total = data.get("total") or 0
                if len(batch) < self.PAGE or (page + 1) * self.PAGE >= total:
                    break
        return raw

    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        host, _, site, locale = parse_workday_url(self.opt("url"))
        prefix = f"https://{host}/" + (f"{locale}/" if locale else "") + site
        posts = []
        for jp in raw_data:
            path = jp.get("externalPath")
            title = clean_ws(jp.get("title"))
            if not path or not title:
                continue
            posts.append(self.make(
                title=title, url=prefix + path, location=jp.get("locationsText"),
                date_posted=parse_posted(jp.get("postedOn")),
                description_snippet=" | ".join(jp.get("bulletFields") or []),
                extra={"wd_path": path},
            ))
        return posts

    async def fetch_detail(self, post: JobPostSchema) -> str | None:
        host, tenant, site, _ = parse_workday_url(self.opt("url"))
        path = post.extra.get("wd_path") or "/job/" + urlsplit(post.url).path.split("/job/", 1)[-1]
        return await workday_api_detail(self.http, host, tenant, site, path, post)


async def workday_api_detail(http: Any, host: str, tenant: str, site: str, path: str,
                             post: JobPostSchema) -> str:
    """Read a posting through Workday's JSON API (the HTML page is an empty JavaScript shell).

    A removed posting answers 404 (raised as FetchError). A closed one has canApply=false or a
    posting end date in the past; both are recorded in post.extra["closed"].
    """
    data = await http.get_json(f"https://{host}/wday/cxs/{tenant}/{site}{path}",
                               headers={"Accept": "application/json"})
    info = data.get("jobPostingInfo", {}) or {}
    end = parse_iso_datetime(info.get("endDate"))
    if info.get("canApply") is False:
        post.extra["closed"] = "applications closed (Workday says it can no longer be applied to)"
    elif end and end < today():
        post.extra["closed"] = f"posting ended on {end:%d %b %Y}"
    if end and not post.deadline:
        post.deadline, post.deadline_text = end, f"Posting end date {end:%d %b %Y}"
    parts = [info.get("title", ""), info.get("location", ""), info.get("timeType", ""),
             html_to_text(info.get("jobDescription", ""))]
    return clean_ws(" \n ".join(p for p in parts if p))


def workday_parts_from_url(url: str) -> tuple[str, str, str, str] | None:
    """https://ubc.wd10.myworkdayjobs.com/en-US/ubcstaffjobs/job/X/Y_JR1 -> (host, tenant, site, '/job/X/Y_JR1')."""
    if "myworkdayjobs.com" not in urlsplit(url).netloc or "/job/" not in url:
        return None
    try:
        host, tenant, site, _ = parse_workday_url(url)
    except ValueError:
        return None
    return host, tenant, site, "/job/" + urlsplit(url).path.split("/job/", 1)[1]


@register
class VarbiScraper(LinkScanScraper):
    """Varbi listing pages: links look like /en/what:job/jobID:123456/ (or jobs.<org>.se/.../-123456.html)."""

    type_name = "varbi"

    def opt(self, key: str, default: Any = None) -> Any:
        if key == "link_pattern":
            return self.cfg.opt(key) or r"(what:job/jobID:\d+|/job/[^/]+/[^/]+-\d+\.html)"
        if key == "bare_date_is_deadline":  # Varbi tables: last column is "Last application date"
            return self.cfg.opt(key, True)
        return super().opt(key, default)


# ------------------------------------------------------------------------------------------
async def render_page(url: str, wait_for: str | None = None, timeout_ms: int = 45000) -> str:
    """Render a JS-heavy page with headless Chromium and return the final HTML."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Playwright not installed: pip install playwright && playwright install chromium") from exc
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page(locale="en-GB")
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if wait_for:
                await page.wait_for_selector(wait_for, timeout=timeout_ms)
            else:
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:  # noqa: BLE001 - some boards never go idle; take what we have
                    pass
            return await page.content()
        finally:
            await browser.close()

