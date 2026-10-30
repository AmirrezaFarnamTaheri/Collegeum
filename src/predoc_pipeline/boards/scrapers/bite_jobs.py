"""Read official public B-ite career searches without executing the site's JavaScript.

ZEW embeds a public jobs widget in its HTML. The listing itself loads via the
provider's read-only search endpoint; no postings are present in the raw HTML.
The public browser client key is discovered from ZEW's published widget script,
rather than stored as a credential or hardcoded into our repository.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar
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
    expected_job_host: ClassVar[str] = "jobs.zew.de"

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
        host = self.opt("job_host", self.expected_job_host)
        if host != self.expected_job_host:
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


_HELMHOLTZ_WIDGET = (
    "https://cs-assets.b-ite.com/helmholtz-zentrum-muenchen/jobs-api/main-listing-de.js"
)
_HELMHOLTZ_ORIGIN = "https://www.helmholtz-munich.de/karriere/stellenangebote"
_HELMHOLTZ_KEY = re.compile(r"""\bvar\s+apiKey\s*=\s*["']([a-f0-9]{40})["']""", re.I)
_HELMHOLTZ_CALL = re.compile(
    r'api\("([^"]+)",\s*(\d+),\s*"[^"]+",\s*"([^"]+)",\s*"([^"]+)"'
)


def _public_field(value: object) -> str:
    if isinstance(value, str):
        return value.strip()[:240]
    if isinstance(value, list) and all(isinstance(part, str) for part in value):
        return ", ".join(part.strip() for part in value if part.strip())[:240]
    return ""


@register
class HelmholtzBiteScraper(BiteJobsScraper):
    """Read Helmholtz Munich's official German B-ite job index without a browser.

    Unlike the ZEW feed this listing uses the custom.Zuordnung filter and
    its publicly advertised widget declares a different var apiKey format.
    The Life Sciences classifier decides which roles are eligible doctorates.
    """

    type_name = "helmholtz_bite_jobs"
    expected_job_host: ClassVar[str] = "jobs.helmholtz-muenchen.de"

    async def fetch_raw_postings(self) -> list[Any]:
        if (
            self.name != "life_special_de_helmholtz_munich"
            or self.opt("widget_url") != _HELMHOLTZ_WIDGET
            or self.opt("url") != _HELMHOLTZ_ORIGIN
            or self.opt("origin") != _HELMHOLTZ_ORIGIN
            or self.opt("api_url") != _SEARCH_API
            or self.opt("job_host") != self.expected_job_host
        ):
            raise ValueError("Invalid official Helmholtz Munich recruitment source configuration")

        max_pages = self.opt("max_pages", 3)
        if type(max_pages) is not int or not 1 <= max_pages <= 4:
            raise ValueError("Helmholtz B-ite pagination budget must be 1-4")

        widget = await self.http.get_text(_HELMHOLTZ_WIDGET)
        key = _HELMHOLTZ_KEY.search(widget)
        call = _HELMHOLTZ_CALL.search(widget)
        if key is None or call is None:
            raise ValueError("Helmholtz B-ite public recruitment widget contract changed")
        listing_name, channel_raw, category, language = call.groups()
        channel = int(channel_raw)
        if (
            listing_name != "main-listing-de" or category != "Homepage_deutsch"
            or language != "de" or channel not in (0, 1)
        ):
            raise ValueError("Unexpected Helmholtz B-ite public listing identity")

        rows: list[Any] = []
        seen: set[str] = set()
        offset = 0
        self.verified_empty_evidence = False
        for _ in range(max_pages):
            payload = {
                "key": key.group(1), "channel": channel, "locale": language,
                "sort": {"by": "title", "order": "asc"},
                "filter": {
                    "locale": {"in": ["en", "de"]},
                    "custom.Zuordnung": {"in": [category]},
                },
                "origin": _HELMHOLTZ_ORIGIN, "page": {"offset": offset},
            }
            try:
                response = await self.http.post_json(_SEARCH_API, payload)
            except Exception as exc:
                self.discovery_fetch_errors.append(type(exc).__name__)
                if not rows:
                    raise
                break
            if not isinstance(response, dict) or not isinstance(
                response.get("jobPostings"), list,
            ):
                self.discovery_parse_errors.append("Invalid Helmholtz B-ite job listing JSON")
                break
            page = response.get("page")
            if not isinstance(page, dict) or (
                type(page.get("total")) is not int
                or not 0 <= page["total"] <= 10000
                or type(page.get("offset")) is not int
                or page["offset"] != offset
            ):
                self.discovery_parse_errors.append("Invalid Helmholtz B-ite paging metadata")
                break
            batch = response["jobPostings"]
            ids = {
                item["id"] for item in batch
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            if seen.intersection(ids):
                self.discovery_parse_errors.append("Repeated Helmholtz B-ite vacancy page")
                break
            seen.update(ids)
            rows.extend(batch)
            offset += len(batch)
            if offset >= page["total"]:
                self.verified_empty_evidence = not rows and page["total"] == 0
                return rows
            if not batch:
                self.discovery_parse_errors.append("Incomplete Helmholtz B-ite pagination")
                break
        else:
            self.discovery_limits.append("Helmholtz B-ite page cap reached")
        return rows

    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        postings = super().parse_postings(raw_data)
        by_url = {post.url: post for post in postings}
        for item in raw_data:
            if not isinstance(item, dict):
                continue
            post = by_url.get(item.get("url")) if isinstance(item.get("url"), str) else None
            custom = item.get("custom")
            if post is None or not isinstance(custom, dict):
                continue
            field = _public_field(custom.get("Forschungsbereich"))
            department = _public_field(custom.get("Institut"))
            location = _public_field(custom.get("place"))
            if field:
                post.fields_of_research = field
            if department:
                post.department = department
            if location:
                post.location = location
        return postings
