"""Polite HTTP client: conditional GET, per-host pacing, robots.txt.

Three behaviours the reviewed implementation lacked, all of which matter for a
crawler that runs unattended every day against other people's infrastructure:

* **Conditional GET.** Feeds ship ``ETag`` and ``Last-Modified``. Storing them
  turns an unchanged daily poll into a 304 with no body, which cuts bandwidth,
  cuts parse time, and -- because the body hash is also stored -- lets the
  pipeline skip a whole source that has not moved.

* **Per-host pacing.** Requests to the same host are spaced out. Firing a
  directory of fifty institutional portals as fast as the socket allows is how
  a well-intentioned aggregator earns a block.

* **robots.txt.** Checked with stdlib ``urllib.robotparser`` and cached per
  host for the run. A syndicated RSS feed is published to be read by machines;
  an HR portal's search pages often are not. Honouring the file is both the
  courteous default and the thing that keeps access working.

The descriptive User-Agent with a contact address is deliberate: an operator
who wants the traffic to stop should be able to find you before they reach for
a firewall rule.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from ..core.urls import content_hash, registrable_host, url_hash
from ..logging_setup import get_logger

log = get_logger(__name__)

__all__ = ["FetchResult", "PoliteClient"]


@dataclass(slots=True)
class FetchResult:
    url: str
    status: int
    text: str = ""
    content: bytes = b""
    from_cache: bool = False
    unchanged: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error

    @property
    def skipped(self) -> bool:
        """304, an unchanged body, or a robots.txt refusal."""
        return self.unchanged or self.status in (304, 999)


@dataclass
class PoliteClient:
    """Wraps httpx with caching, pacing and robots.txt compliance."""

    user_agent: str
    timeout: float = 25.0
    per_host_delay: float = 1.0
    respect_robots: bool = True
    store: Any | None = None
    client: httpx.Client | None = None
    _last_request: dict[str, float] = field(default_factory=dict)
    _robots: dict[str, RobotFileParser | None] = field(default_factory=dict)
    _owns_client: bool = False

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": (
                        "application/rss+xml, application/atom+xml, application/xml;q=0.9, "
                        "text/html;q=0.8, */*;q=0.5"
                    ),
                    "Accept-Language": "en;q=0.9, *;q=0.5",
                },
            )
            self._owns_client = True

    def close(self) -> None:
        if self._owns_client and self.client is not None:
            self.client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- robots -----------------------------------------------------------
    def _robots_for(self, url: str) -> RobotFileParser | None:
        host = registrable_host(url)
        if host in self._robots:
            return self._robots[host]
        parser: RobotFileParser | None = None
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        try:
            response = self.client.get(robots_url, timeout=10.0)  # type: ignore[union-attr]
            if response.status_code == 200:
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
        except Exception:
            parser = None  # unreachable robots.txt is treated as "no rules"
        self._robots[host] = parser
        return parser

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parser = self._robots_for(url)
        if parser is None:
            return True
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:  # pragma: no cover - defensive
            return True

    # -- pacing -----------------------------------------------------------
    def _pace(self, url: str, sleep: Callable[[float], None] = time.sleep) -> None:
        host = registrable_host(url)
        elapsed = time.monotonic() - self._last_request.get(host, 0.0)
        if elapsed < self.per_host_delay:
            sleep(self.per_host_delay - elapsed)
        self._last_request[host] = time.monotonic()

    # -- fetching ---------------------------------------------------------
    def get(
        self, url: str, *, use_cache: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> FetchResult:
        """Fetch a URL, returning a result object rather than raising."""
        if not self.allowed(url):
            return FetchResult(url=url, status=999, error="blocked by robots.txt")

        headers: dict[str, str] = {}
        key = url_hash(url)
        cached = None
        if use_cache and self.store is not None:
            cached = self.store.http_cache_get(key)
            if cached is not None:
                if cached["etag"]:
                    headers["If-None-Match"] = cached["etag"]
                if cached["last_modified"]:
                    headers["If-Modified-Since"] = cached["last_modified"]

        self._pace(url, sleep=sleep)
        try:
            response = self.client.get(url, headers=headers)  # type: ignore[union-attr]
        except httpx.RequestError as exc:
            return FetchResult(url=url, status=0, error=f"transport: {exc}")

        if response.status_code == 304:
            self._remember(key, url, response, body_hash=None)
            return FetchResult(url=url, status=304, from_cache=True, unchanged=True)

        if response.status_code != 200:
            self._remember(key, url, response, body_hash=None)
            return FetchResult(
                url=url, status=response.status_code, error=f"HTTP {response.status_code}"
            )

        text = response.text
        digest = content_hash(text)
        unchanged = bool(cached is not None and cached["body_hash"] == digest)
        self._remember(key, url, response, body_hash=digest)
        return FetchResult(
            url=url,
            status=200,
            text=text,
            content=response.content,
            unchanged=unchanged,
        )

    def _remember(
        self, key: str, url: str, response: httpx.Response, *, body_hash: str | None
    ) -> None:
        if self.store is None:
            return
        try:
            self.store.http_cache_put(
                key,
                url,
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
                body_hash=body_hash,
                status=response.status_code,
            )
        except Exception as exc:  # pragma: no cover - cache is advisory
            log.debug("Failed to record http cache metadata for %s: %s", url, exc)
