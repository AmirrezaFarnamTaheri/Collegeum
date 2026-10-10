"""Base scraper contract + registry."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from ..config import SourceConfig
from ..http import HttpClient
from ..models import JobPostSchema
from ..utils.text import html_to_text

log = logging.getLogger(__name__)

SCRAPERS: dict[str, type[BaseScraper]] = {}


class SourceSkipped(Exception):
    """Raised when a source cannot run for a benign reason (e.g. missing optional credentials)."""


class DiscoveryFetchError(RuntimeError):
    """Source discovery could not obtain its payload."""


class DiscoveryParseError(RuntimeError):
    """A source payload could not be parsed into postings."""


def register(cls: type[BaseScraper]) -> type[BaseScraper]:
    SCRAPERS[cls.type_name] = cls
    return cls


class BaseScraper(ABC):
    """Each scraper = fetch raw data (network) + parse it (pure, unit-testable)."""

    type_name: ClassVar[str] = "base"

    def __init__(self, cfg: SourceConfig, http: HttpClient):
        self.cfg = cfg
        self.http = http
        self.discovery_fetch_errors: list[str] = []
        self.discovery_parse_errors: list[str] = []
        self.discovery_limits: list[str] = []
        if cfg.min_interval is not None:
            for u in self.urls():
                http.set_host_interval(u, cfg.min_interval)

    # -- helpers -------------------------------------------------------------------------
    @property
    def name(self) -> str:
        return self.cfg.name

    def opt(self, key: str, default: Any = None) -> Any:
        return self.cfg.opt(key, default)

    def urls(self) -> list[str]:
        urls = self.opt("urls") or ([self.opt("url")] if self.opt("url") else [])
        return [u for u in urls if u]

    async def fetch_each(self, fn: Any) -> list[Any]:
        """Call `await fn(url)` for every configured URL; one dead URL doesn't sink the source."""
        out, errors = [], []
        for u in self.urls():
            try:
                out.append(await fn(u))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{u}: {exc}")
                self.discovery_fetch_errors.append(type(exc).__name__)
                log.warning("%s: %s failed: %s", self.name, u, exc)
        if errors and not out:
            raise RuntimeError("; ".join(errors)[:500])
        return out

    def make(self, **kw: Any) -> JobPostSchema:
        """Build a JobPostSchema with source-level defaults applied."""
        kw.setdefault("source", self.name)
        extra = kw.setdefault("extra", {})
        if not kw.get("institution") and self.cfg.institution:
            kw["institution"] = self.cfg.institution
            extra["source_institution_default"] = True
        if not kw.get("country") and self.cfg.country:
            kw["country"] = self.cfg.country
            # Flag so detail-page heuristics can override with actual job location (F03).
            extra["source_country_default"] = True
        kw.setdefault("field_implied", self.cfg.field_implied)
        if self.opt("employer_required"):
            extra["employer_required"] = True
        return JobPostSchema(**kw)

    # -- contract ------------------------------------------------------------------------
    @abstractmethod
    async def fetch_raw_postings(self) -> list[Any]:
        """Network I/O only. Return whatever parse_postings needs (HTML strings, JSON dicts...)."""

    @abstractmethod
    def parse_postings(self, raw_data: list[Any]) -> list[JobPostSchema]:
        """Pure parsing: raw payloads -> normalised postings."""

    async def run(self) -> tuple[list[JobPostSchema], int]:
        self.discovery_fetch_errors.clear()
        self.discovery_parse_errors.clear()
        self.discovery_limits.clear()
        try:
            raw = await self.fetch_raw_postings()
        except SourceSkipped:
            raise
        except Exception as exc:
            raise DiscoveryFetchError(str(exc)) from exc
        try:
            posts = self.parse_postings(raw)
        except Exception as exc:
            raise DiscoveryParseError(str(exc)) from exc
        # de-duplicate within a single source run
        seen, unique = set(), []
        for p in posts:
            if p.url and p.title and p.url not in seen:
                seen.add(p.url)
                unique.append(p)
        return unique, len(unique)

    async def fetch_detail(self, post: JobPostSchema) -> str | None:
        """Return plain text of the posting's detail page (used by the enricher).

        Raises core.http.FetchError with .status 404/410 when the posting is gone.
        """
        return await generic_fetch_detail(self.http, post)


async def generic_fetch_detail(http: HttpClient, post: JobPostSchema) -> str | None:
    """GET the job URL (following bit.ly & co.), remember where it landed, return its text.

    If the link lands on a Workday career site, the page itself is an empty JavaScript shell,
    so the posting is read through Workday's JSON API instead (which also tells us if it closed).
    """
    from .university_ats import workday_api_detail, workday_parts_from_url  # avoid import cycle

    direct = workday_parts_from_url(post.url)
    if direct:
        post.extra["final_url"] = post.url
        return await workday_api_detail(http, *direct, post)
    resp = await http.request("GET", post.url)
    final = str(resp.url)
    post.extra["final_url"] = final
    wd = workday_parts_from_url(final)
    if wd:
        return await workday_api_detail(http, *wd, post)

    from ...utils.pdf import extract_pdf_text, is_pdf

    content_type = resp.headers.get("content-type", "")
    if is_pdf(resp.content, content_type, final):
        pdf_text = extract_pdf_text(resp.content, max_chars=20000)
        if pdf_text:
            return pdf_text

    return html_to_text(resp.text, max_chars=20000)
