"""Server-rendered vacancy tables whose URL column contains plain text."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ..models import JobPostSchema
from ..utils.dates import extract_deadline
from ..utils.text import clean_ws, truncate
from .base import BaseScraper, register


@register
class TextTableScraper(BaseScraper):
    """Configured columns are zero-based; URLs must use the source's HTTPS host."""

    type_name = "text_table"

    async def fetch_raw_postings(self) -> list[Any]:
        async def get(url: str) -> tuple[str, str]:
            return url, await self.http.get_text(url)

        return await self.fetch_each(get)

    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        columns: dict[str, int] = self.opt("columns")
        if not columns or not {"title", "url"} <= columns.keys():
            raise ValueError("text_table requires title and url columns")
        if any(isinstance(i, bool) or not isinstance(i, int) or i < 0 for i in columns.values()):
            raise ValueError("text_table column indexes must be nonnegative integers")
        posts = []
        for base, html in raw_data:
            soup = BeautifulSoup(html, "lxml")
            table = soup.select_one(self.opt("table_selector"))
            if table is None:
                self.discovery_parse_errors.append("vacancy table missing")
                continue
            for row in table.select("tr"):
                cells = row.find_all("td", recursive=False)
                if not cells:  # header
                    continue
                if len(cells) <= max(columns.values()):
                    self.discovery_parse_errors.append("incomplete vacancy row")
                    continue
                values = {
                    key: clean_ws(cells[index].get_text(" ")) for key, index in columns.items()
                }
                title, url = values["title"], values["url"]
                try:
                    parts = urlsplit(url)
                except ValueError:
                    self.discovery_parse_errors.append("invalid vacancy title or URL")
                    continue
                if (
                    not title
                    or parts.scheme != "https"
                    or parts.username
                    or parts.password
                    or parts.netloc != urlsplit(base).netloc
                    or not parts.path.startswith(self.opt("job_path_prefix", "/"))
                ):
                    self.discovery_parse_errors.append("invalid vacancy title or URL")
                    continue
                raw_deadline = values.get("deadline")
                deadline, deadline_text = (
                    extract_deadline(f"deadline: {raw_deadline}") if raw_deadline else (None, None)
                )
                posts.append(
                    self.make(
                        title=title,
                        url=url,
                        location=values.get("location"),
                        department=values.get("department"),
                        deadline=deadline,
                        deadline_text=deadline_text or raw_deadline,
                        description_snippet=truncate(row.get_text(" ", strip=True), 500),
                    )
                )
        return posts
