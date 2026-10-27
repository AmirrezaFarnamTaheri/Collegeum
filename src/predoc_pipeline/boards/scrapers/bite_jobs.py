"""Read official public B-ite career searches without executing the site's JavaScript.

ZEW embeds a public jobs widget in its HTML. The listing itself loads via the
provider's read-only search endpoint; no postings are present in the raw HTML.
The public browser client key is discovered from ZEW's published widget script,
rather than stored as a credential or hardcoded into our repository.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from ..models import JobPostSchema
from ..utils.dates import parse_iso_datetime
from ..utils.text import html_to_text, truncate
from .base import BaseScraper, register

_KEY = re.compile(r"""\bkey\s*:\s*["']([a-fA-F0-9]{40})["']""")
_ID = re.compile(r"[a-f0-9]{40}", re.I)
_PATH = re.compile(r"/jobposting/[a-f0-9]{40,41}/?$", re.I)
_SEARCH_API = "https://jobs.b-ite.com/api/v1/postings/search"
_WIDGET_HOST = "cs-assets.b-ite.com"


def _valid_posting_url(url: object, host: str, job_id: str) -> bool:
    """Reject third-party/redirect links; require the provider's exact job identity."""
    if not isinstance(url, str) or not url or any(c.isspace() for c in url):
        return False
    try:
        parts = urlsplit(url)
        path = parts.path
        return (
            parts.scheme == "https"
            and parts.hostname == host
            and parts.username is None
            and parts.password is None
            and parts.port in (None, 443)
            and not parts.query
            and not parts.fragment
            and bool(_PATH.fullmatch(path))
            and path.removeprefix("/jobposting/").lower().startswith(job_id.lower())
        )
    except ValueError:
        return False


@register
class BiteJobsScraper(BaseScraper):
    """Parse the same public search response used by ZEW's B-ite embedded widget."""

    type_name = "bite_jobs"

    async def fetch_raw_postings(self) -> list[Any]:
        widget = self.opt("widget_url")
        api = self.opt("api_url", _SEARCH_API)
        origin = self.opt("origin")
        category = self.opt("category")
        if (
            not isinstance(widget, str)
            or not widget.startswith("https://cs-assets.b-ite.com/")
            or not widget.endswith(".js")
            or api != _SEARCH_API
            or not isinstance(origin, str)
            or not origin.startswith("https://www.zew.de/")
            or not isinstance(category, str)
            or not re.fullmatch(r"[a-z0-9-]+", category)
        ):
            raise ValueError("Invalid B-ite public source configuration")

        script = await self.http.get_text(widget)
        key = _KEY.search(script)
        if key is None:
            self.discovery_parse_errors.append("Missing B-ite public widget key")
            raise ValueError("B-ite public widget configuration unavailable")

        max_pages = int(self.opt("max_pages", 10))
        if max_pages < 1 or max_pages > 100:
            raise ValueError("B-ite max_pages must be between 1 and 100")

        rows: list[Any] = []
        offset = 0
        seen_ids: set[str] = set()
        for _ in range(max_pages):
            payload = {
                "key": key.group(1),
                "channel": 0,
                "locale": "de",
                "sort": {"by": "startsOn", "order": "desc"},
                "filter": {
                    "custom.zuordnung_homepage": {"in": [category]},
                    "locale": {"in": ["*"]},
                },
                "origin": origin,
                "page": {"offset": offset},
            }
            try:
                data = await self.http.post_json(api, payload)
            except Exception as exc:
                self.discovery_fetch_errors.append(type(exc).__name__)
                if not rows:
                    raise
                break
            if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list):
                self.discovery_parse_errors.append("Invalid B-ite search response")
                break
            page = data.get("page")
            if not isinstance(page, dict):
                self.discovery_parse_errors.append("Missing B-ite pagination metadata")
                break
            total = page.get("total")
            if (type(total) is not int or total < 0 or
                    type(page.get("offset")) is not int or page["offset"] != offset):
                self.discovery_parse_errors.append("Inconsistent B-ite pagination metadata")
                break
            batch = data["jobPostings"]
            ids = {
                p["id"] for p in batch if isinstance(p, dict)
                and isinstance(p.get("id"), str)
            }
            if seen_ids.intersection(ids):
                self.discovery_parse_errors.append("Repeated B-ite pagination page")
                break
            seen_ids.update(ids)
            rows.extend(batch)
            offset += len(batch)
            if offset >= total:
                return rows
            if not batch:
                self.discovery_parse_errors.append("Incomplete B-ite pagination result")
                break
        else:
            self.discovery_limits.append("B-ite pagination cap reached")
        return rows

    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        host = self.opt("job_host", "jobs.zew.de")
        if host != "jobs.zew.de":
            raise ValueError("Unexpected B-ite vacancy hostname")
        posts = []
        for item in raw_data:
            if not isinstance(item, dict):
                self.discovery_parse_errors.append("Invalid B-ite vacancy object")
                continue
            job_id, url, title = item.get("id"), item.get("url"), item.get("title")
            if (
                not isinstance(job_id, str)
                or not _ID.fullmatch(job_id)
                or not _valid_posting_url(url, host, job_id)
                or not isinstance(title, str)
                or not title.strip()
            ):
                self.discovery_parse_errors.append("Invalid B-ite vacancy identity or link")
                continue
            starts_on, ends_on = item.get("startsOn"), item.get("endsOn")
            if (starts_on is not None and not isinstance(starts_on, str)
                    or ends_on is not None and not isinstance(ends_on, str)):
                self.discovery_parse_errors.append("Invalid B-ite vacancy dates")
                continue
            custom = item.get("custom") or {}
            if not isinstance(custom, dict):
                self.discovery_parse_errors.append("Invalid B-ite vacancy metadata")
                continue
            description = item.get("description")
            summary = (
                truncate(html_to_text(description), 500)
                if isinstance(description, str) else ""
            )
            deadline = parse_iso_datetime(ends_on)
            try:
                posts.append(self.make(
                    title=title, url=url,
                    date_posted=parse_iso_datetime(starts_on),
                    deadline=deadline,
                    deadline_text=f"Employer listing ends {deadline:%d %b %Y}" if deadline else None,
                    description_snippet=summary,
                    extra={"bite_job_id": job_id},
                ))
            except (TypeError, ValueError, OverflowError):
                self.discovery_parse_errors.append("Unparseable B-ite vacancy")
        return posts
