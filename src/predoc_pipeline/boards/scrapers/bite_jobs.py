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

_HELMHOLTZ_KEY = re.compile(r"""var\s+apiKey\s*=\s*['"]([a-fA-F0-9]{40})['"]""")
_HELMHOLTZ_EN = (
    "https://cs-assets.b-ite.com/helmholtz-zentrum-muenchen/"
    "jobs-api/main-listing-en.js"
)
_HELMHOLTZ_DE = (
    "https://cs-assets.b-ite.com/helmholtz-zentrum-muenchen/"
    "jobs-api/main-listing-de.js"
)
_HELMHOLTZ_SITE = "https://www.helmholtz-munich.de/en/career/jobs"
_HELMHOLTZ_DE_SITE = "https://www.helmholtz-munich.de/karriere/stellenangebote"
_HELMHOLTZ_JOB_HOST = "jobs.helmholtz-muenchen.de"
_HELMHOLTZ_COHORTS = (
    ("main-listing-en", "Homepage_englisch", "en",
     _HELMHOLTZ_EN, _HELMHOLTZ_SITE),
    ("main-listing-de", "Homepage_deutsch", "de",
     _HELMHOLTZ_DE, _HELMHOLTZ_DE_SITE),
)



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

    async def _fetch_helmholtz(self) -> list[Any]:
        """Read both publisher-declared job cohorts without duplicate identities.

        The employer's public B-ite widget exposes the API key, locale,
        listing channel, recruitment filter and exact official vacancy host.
        A successful page with only staff roles is not a PhD match.
        """
        if (
            self.opt("widget_url") != _HELMHOLTZ_EN
            or self.opt("url") != _HELMHOLTZ_SITE
            or self.opt("origin") != _HELMHOLTZ_SITE
            or self.opt("api_url") != _SEARCH_API
            or self.opt("job_host") != _HELMHOLTZ_JOB_HOST
        ):
            raise ValueError("Unexpected Helmholtz B-ite public source configuration")
        max_pages = int(self.opt("max_pages", 3))
        if max_pages < 1 or max_pages > 10:
            raise ValueError("Helmholtz B-ite max_pages must be 1..10")

        unique: dict[str, Any] = {}
        valid_cohorts = 0
        for name, category, locale, widget, origin in _HELMHOLTZ_COHORTS:
            try:
                script = await self.http.get_text(widget)
            except Exception as exc:  # noqa: BLE001 - other language may still work
                self.discovery_fetch_errors.append(type(exc).__name__)
                continue
            public_key = _HELMHOLTZ_KEY.search(script)
            required_call = f'api("{name}", 0, "homepage", "{category}", "{locale}",'
            if public_key is None or required_call not in script:
                self.discovery_parse_errors.append(
                    "Helmholtz public recruitment widget contract changed"
                )
                continue
            offset = 0
            cohort_valid = False
            for _ in range(max_pages):
                payload = {
                    "key": public_key.group(1), "channel": 0,
                    "locale": locale,
                    "sort": {"by": "title", "order": "asc"},
                    "filter": {
                        "locale": {"in": ["en", "de"]},
                        "custom.Zuordnung": {"in": [category]},
                    },
                    "origin": origin, "page": {"offset": offset},
                }
                try:
                    data = await self.http.post_json(_SEARCH_API, payload)
                except Exception as exc:  # noqa: BLE001 - retain valid other pages
                    self.discovery_fetch_errors.append(type(exc).__name__)
                    break
                if not isinstance(data, dict) or not isinstance(
                    data.get("jobPostings"), list
                ):
                    self.discovery_parse_errors.append(
                        "Invalid Helmholtz public recruitment response"
                    )
                    break
                page = data.get("page")
                if not isinstance(page, dict):
                    self.discovery_parse_errors.append("Missing Helmholtz pagination")
                    break
                total = page.get("total")
                if (
                    type(total) is not int or total < 0
                    or type(page.get("offset")) is not int
                    or page["offset"] != offset
                ):
                    self.discovery_parse_errors.append(
                        "Invalid Helmholtz pagination metadata"
                    )
                    break
                cohort_valid = True
                batch = data["jobPostings"]
                for item in batch:
                    # Invalid objects remain visible to the common parser,
                    # rather than disappearing as a false healthy-empty feed.
                    identity = item.get("id") if isinstance(item, dict) else None
                    key = identity if isinstance(identity, str) else (
                        f"invalid-{len(unique)}"
                    )
                    if key not in unique:
                        unique[key] = item
                offset += len(batch)
                if offset >= total:
                    break
                if not batch:
                    self.discovery_parse_errors.append(
                        "Incomplete Helmholtz pagination"
                    )
                    break
            else:
                self.discovery_limits.append("Helmholtz B-ite page cap reached")
            if cohort_valid:
                valid_cohorts += 1

        if not valid_cohorts:
            raise ValueError("No valid public Helmholtz recruitment cohort")
        return list(unique.values())

    async def fetch_raw_postings(self) -> list[Any]:
        profile = self.opt("site_profile")
        if profile == "helmholtz_munich":
            return await self._fetch_helmholtz()
        if profile not in (None, "zew"):
            raise ValueError("Unknown B-ite source profile")
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
        profile = self.opt("site_profile")
        expected = (
            _HELMHOLTZ_JOB_HOST if profile == "helmholtz_munich"
            else "jobs.zew.de"
        )
        host = self.opt("job_host", expected)
        if host != expected:
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
