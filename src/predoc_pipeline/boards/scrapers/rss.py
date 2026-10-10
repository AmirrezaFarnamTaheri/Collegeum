"""Generic RSS/Atom scraper (Inomics, The Economic Misfit, Substack job digests, jobs.ac.uk feeds...)."""
from __future__ import annotations

import time
from datetime import date
from typing import Any

import feedparser

from ..models import JobPostSchema
from ..utils.dates import extract_deadline, parse_date
from ..utils.text import clean_ws, html_to_text, split_role_at_institution, truncate
from .base import BaseScraper, register


def _entry_date(entry: Any) -> date | None:
    for key in ("published_parsed", "updated_parsed"):
        st = entry[key] if key in entry else None
        if st:
            return date.fromtimestamp(time.mktime(st))
    return parse_date(entry.get("published") or entry.get("updated"))


@register
class RSSScraper(BaseScraper):
    """Options:
    url / urls                 feed URL(s)
    include_url_contains       keep entries whose link contains any of these (e.g. ["/job/"])
    exclude_url_contains       drop entries whose link contains any of these
    categories_exclude         drop entries tagged with any of these categories (substring, case-insens.)
    title_format               "plain" | "role_at_institution" ("RA in X at LSE (UK)")
    """

    type_name = "rss"

    async def fetch_raw_postings(self) -> list[Any]:
        return await self.fetch_each(self.http.get_text)

    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        inc = [s.lower() for s in self.opt("include_url_contains", [])]
        exc = [s.lower() for s in self.opt("exclude_url_contains", [])]
        cat_exc = [s.lower() for s in self.opt("categories_exclude", [])]
        split_title = self.opt("title_format", "plain") == "role_at_institution"
        posts: list[JobPostSchema] = []
        for xml in raw_data:
            feed = feedparser.parse(xml)
            if not feed.version or (feed.bozo and not feed.entries):
                self.discovery_parse_errors.append("response is not a parseable RSS/Atom feed")
                continue
            if feed.bozo:
                self.discovery_parse_errors.append("malformed feed with recoverable entries")
            for e in feed.entries:
                link = e.get("link") or ""
                low = link.lower()
                if inc and not any(s in low for s in inc):
                    continue
                if exc and any(s in low for s in exc):
                    continue
                cats = [clean_ws(t.get("term", "")) for t in e.get("tags", []) or []]
                if cat_exc and any(c in cat.lower() for cat in cats for c in cat_exc):
                    continue
                title = clean_ws(e.get("title", ""))
                if not title or not link:
                    self.discovery_parse_errors.append("feed entry lacks title or link")
                    continue
                institution, location = None, None
                if split_title:
                    title, institution, location = split_role_at_institution(title)
                summary_html = e.get("summary") or e.get("description") or ""
                if e.get("content"):
                    summary_html = e["content"][0].get("value", summary_html)
                text = html_to_text(summary_html) if "<" in summary_html else clean_ws(summary_html)
                deadline, deadline_text = extract_deadline(text)
                try:
                    post = self.make(
                        title=title, url=link, institution=institution or "", location=location,
                        date_posted=_entry_date(e), deadline=deadline, deadline_text=deadline_text,
                        description_snippet=truncate(text, 600),
                        extra={"categories": cats} if cats else {},
                    )
                except (ValueError, OverflowError):
                    self.discovery_parse_errors.append("feed entry has invalid posting fields")
                    continue
                posts.append(post)
        return posts
