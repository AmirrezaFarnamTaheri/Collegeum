"""Read the JSON vacancy array embedded in Aarhus's official careers page."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import JobPostSchema
from .base import BaseScraper, register

_ASSIGNMENT = re.compile(r"\bDYCON\.EmplyData\.[A-Za-z0-9_]+\.vacancies\s*=\s*")


@register
class EmplyEmbeddedScraper(BaseScraper):
    """Decode JSON data only; never execute the page's JavaScript."""

    type_name = "emply_embedded"

    async def fetch_raw_postings(self) -> list[Any]:
        async def get(url: str) -> tuple[str, str]:
            return url, await self.http.get_text(url)

        return await self.fetch_each(get)

    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        posts = []
        for base, html in raw_data:
            arrays = []
            for script in BeautifulSoup(html, "lxml").select("script"):
                content = script.get_text()
                for match in _ASSIGNMENT.finditer(content):
                    try:
                        entries, _ = json.JSONDecoder().raw_decode(content[match.end() :])
                        if not isinstance(entries, list):
                            raise ValueError("vacancies must be an array")
                        arrays.append(entries)
                    except (ValueError, json.JSONDecodeError):
                        self.discovery_parse_errors.append("invalid Emply vacancy array")
            if not arrays:
                self.discovery_parse_errors.append("Emply vacancy array missing")
                continue
            for entries in arrays:
                for entry in entries:
                    try:
                        if not isinstance(entry, dict):
                            raise ValueError("vacancy must be an object")
                        title, path = entry.get("title"), entry.get("link")
                        if (
                            not isinstance(title, str)
                            or not title.strip()
                            or not isinstance(path, str)
                            or not path.startswith(self.opt("job_path_prefix"))
                        ):
                            raise ValueError("invalid vacancy title or path")
                        location = entry.get("location") or {}
                        if not isinstance(location, dict):
                            raise ValueError("invalid location")
                        deadline = entry.get("deadline_date")
                        posted = entry.get("registered_date")
                        posts.append(
                            self.make(
                                title=title,
                                url=urljoin(base, path),
                                location=location.get("name"),
                                department=entry.get("faculty"),
                                deadline=date.fromisoformat(deadline) if deadline else None,
                                deadline_text=f"Application deadline {deadline}"
                                if deadline
                                else None,
                                date_posted=date.fromisoformat(posted) if posted else None,
                            )
                        )
                    except (ValueError, TypeError):
                        self.discovery_parse_errors.append("invalid Emply vacancy entry")
        return posts
