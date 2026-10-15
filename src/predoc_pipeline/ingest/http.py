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
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from ..core.network_safety import UnsafeDestination, validate_public_url
from ..core.urls import content_hash, registrable_host, url_hash
from ..logging_setup import get_logger

log = get_logger(__name__)
MAX_CACHED_BODY_BYTES = 1_000_000
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

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
    _check_dns: bool = False

    def __post_init__(self) -> None:
        self._check_dns = self.client is None or not isinstance(\n            getattr(self.client, "_transport", None), httpx.MockTransport\n        )
        if self.client is None:
            self.client = httpx.Client(
                timeout=self.timeout,
                follow_redirects=False,
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
        parts = urlsplit(url)
        # Robots policies are origin-scoped, not registrable-host scoped.
        # Different schemes and ports can serve different robots.txt files.
        origin = f"{parts.scheme.lower()}://{parts.netloc.lower()}"
        if origin in self._robots:
            return self._robots[origin]
        parser: RobotFileParser | None = None
        robots_url = f"{origin}/robots.txt"
        try:
            validate_public_url(robots_url, resolve_dns=self._check_dns)
            # Stream robots.txt too: a server must not exhaust crawler memory
            # before the job-page response-size guard ever runs.
            with self.client.stream(  # type: ignore[union-attr]
                "GET", robots_url, timeout=10.0, follow_redirects=False,
            ) as response:
                if response.status_code == 200:
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if len(body) + len(chunk) > 256 * 1024:
                            raise UnsafeDestination("robots.txt response too large")
                        body.extend(chunk)
                    parser = RobotFileParser()
                    parser.parse(body.decode("utf-8", errors="replace").splitlines())
                elif response.status_code not in (404, 410):
                    # 403/429, redirects and 5xx are not permission to crawl.
                    parser = RobotFileParser()
                    parser.parse(["User-agent: *", "Disallow: /"])
        except (httpx.RequestError, UnsafeDestination, OSError, ValueError):
            parser = RobotFileParser()
            parser.parse(["User-agent: *", "Disallow: /"])
        self._robots[origin] = parser
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
            return False

    # -- pacing -----------------------------------------------------------
    def _pace(self, url: str, sleep: Callable[[float], None] = time.sleep) -> None:
        host = registrable_host(url)
        elapsed = time.monotonic() - self._last_request.get(host, 0.0)
        if elapsed < self.per_host_delay:
            sleep(self.per_host_delay - elapsed)
        self._last_request[host] = time.monotonic()

    # -- fetching ---------------------------------------------------------
    def _safe_get(self, url: str, headers: dict[str, str],
                  sleep: Callable[[float], None]) -> httpx.Response:
        """Fetch only validated destinations and inspect every redirect hop."""
        current = url
        current_headers = dict(headers)
        for hop in range(6):
            validate_public_url(current, resolve_dns=self._check_dns)
            if hop:
                if not self.allowed(current):
                    raise UnsafeDestination("redirect blocked by robots.txt")
                self._pace(current, sleep=sleep)
            with self.client.stream(  # type: ignore[union-attr]
                "GET", current, headers=current_headers, follow_redirects=False
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise UnsafeDestination("HTTP redirect without location")
                    target = urljoin(current, location)
                    validate_public_url(target, resolve_dns=self._check_dns)
                    if hop >= 5:
                        raise UnsafeDestination("HTTP redirect limit exceeded")
                    origin = urlsplit(current)
                    destination = urlsplit(target)
                    if (origin.scheme, origin.netloc) != (destination.scheme, destination.netloc):
                        # Do not forward vendor-specific credentials or
                        # cache validators to a different HTTP origin.
                        safe_headers = {"user-agent", "accept", "accept-language",
                                        "accept-encoding"}
                        current_headers = {name: value for name, value in current_headers.items()
                                           if name.lower() in safe_headers}
                    current = target
                    continue
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise UnsafeDestination("HTTP response too large")
                # iter_bytes has decoded compressed content already; never
                # forward the original Content-Encoding/Content-Length pair.
                headers_out = {k: v for k, v in response.headers.items()
                               if k.lower() not in {"content-encoding", "content-length",
                                                    "transfer-encoding"}}
                return httpx.Response(
                    response.status_code, headers=headers_out,
                    content=bytes(body), request=response.request,
                )
        raise UnsafeDestination("HTTP redirect limit exceeded")

    def get(
        self, url: str, *, use_cache: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> FetchResult:
        """Fetch a URL, returning a result object rather than raising."""
        try:
            validate_public_url(url, resolve_dns=self._check_dns)
        except UnsafeDestination:
            return FetchResult(url=url, status=0, error="unsafe outbound HTTP destination")
        if not self.allowed(url):
            return FetchResult(url=url, status=999, error="blocked by robots.txt")

        headers: dict[str, str] = {}
        key = url_hash(url)
        cached = None
        if use_cache and self.store is not None:
            cached = self.store.http_cache_get(key)
            # An ETag alone is not a replayable cache. Only send conditional
            # headers if the original body is actually available for parsing.
            if cached is not None and cached["body"] is not None:
                if cached["etag"]:
                    headers["If-None-Match"] = cached["etag"]
                if cached["last_modified"]:
                    headers["If-Modified-Since"] = cached["last_modified"]

        self._pace(url, sleep=sleep)
        try:
            response = self._safe_get(url, headers, sleep)
        except UnsafeDestination as exc:
            return FetchResult(url=url, status=0, error=f"outbound policy: {exc}")
        except httpx.RequestError as exc:
            return FetchResult(url=url, status=0, error=f"transport: {type(exc).__name__}")

        if response.status_code == 304:
            if cached is None or cached["body"] is None:
                # 304 with no replayable body cannot count as a successful
                # collection; the original content might never be processed.
                return FetchResult(url=url, status=0, error="304 without cached body")
            body = bytes(cached["body"])
            self._remember(key, url, response, body_hash=None)
            return FetchResult(
                url=url, status=200, text=body.decode("utf-8", errors="replace"),
                content=body, from_cache=True,
            )

        if response.status_code != 200:
            self._remember(key, url, response, body_hash=None)
            return FetchResult(
                url=url, status=response.status_code, error=f"HTTP {response.status_code}"
            )

        text = response.text
        digest = content_hash(text)
        # Identical bytes do not imply that all previously discovered jobs
        # reached gating/extraction. Replay every readable response.
        self._remember(key, url, response, body_hash=digest)
        return FetchResult(
            url=url, status=200, text=text, content=response.content,
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
                body=(response.text.encode("utf-8")
                      if response.status_code == 200
                      and len(response.content) <= MAX_CACHED_BODY_BYTES else None),
            )
        except Exception as exc:  # pragma: no cover - cache is advisory
            log.debug("Failed to record http cache metadata for %s: %s", url, exc)
