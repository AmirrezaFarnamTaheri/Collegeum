"""Shared async HTTP client: UA rotation, per-host politeness, retries with backoff."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from ..core.network_safety import UnsafeDestination, validate_public_url

log = logging.getLogger(__name__)

DEFAULT_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
]

DEFAULT_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8,de;q=0.7,fr;q=0.6,es;q=0.5",
    "Sec-Ch-Ua": '"Not;A=Brand";v="24", "Chromium";v="128", "Google Chrome";v="128"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

RETRY_STATUS = {429, 500, 502, 503, 504, 520, 522, 524}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class FetchError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class HttpClient:
    def __init__(self, timeout: float = 30.0, max_retries: int = 3, backoff_base: float = 2.0,
                 default_min_interval: float = 1.0, user_agents: list[str] | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.default_min_interval = default_min_interval
        self.user_agents = user_agents or DEFAULT_UAS
        self._mock_transport = transport is not None
        self._host_interval: dict[str, float] = {}
        self._host_last: dict[str, float] = {}
        self._host_lock: dict[str, asyncio.Lock] = {}
        self._client = httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, transport=transport,
            headers={"Accept-Encoding": "gzip, deflate"},
        )

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def set_host_interval(self, url_or_host: str, seconds: float) -> None:
        host = urlsplit(url_or_host).netloc or url_or_host
        self._host_interval[host.lower()] = seconds

    async def _polite_wait(self, host: str) -> None:
        lock = self._host_lock.setdefault(host, asyncio.Lock())
        async with lock:
            interval = self._host_interval.get(host, self.default_min_interval)
            wait = self._host_last.get(host, 0.0) + interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait + random.uniform(0, interval * 0.3))
            self._host_last[host] = time.monotonic()

    async def _safe_fetch(self, method: str, url: str, headers: dict[str, str],
                          **kw: Any) -> httpx.Response:
        """Follow a bounded number of explicitly validated redirects."""
        current = url
        arguments = dict(kw)
        for hop in range(6):
            try:
                validate_public_url(current, resolve_dns=not self._mock_transport)
            except UnsafeDestination as exc:
                raise FetchError(f"Unsafe outbound HTTP destination: {exc}") from exc
            if hop:
                await self._polite_wait(urlsplit(current).netloc.lower())
            async with self._client.stream(
                method, current, headers=headers, follow_redirects=False, **arguments
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise FetchError("HTTP redirect without location",
                                         status=response.status_code)
                    target = urljoin(current, location)
                    try:
                        validate_public_url(target, resolve_dns=not self._mock_transport)
                    except UnsafeDestination as exc:
                        raise FetchError(f"Unsafe redirect destination: {exc}") from exc
                    if hop >= 5:
                        raise FetchError("HTTP redirect limit exceeded")
                    origin = urlsplit(current)
                    destination = urlsplit(target)
                    if (origin.scheme, origin.netloc) != (destination.scheme, destination.netloc):
                        if method.upper() not in {"GET", "HEAD"}:
                            raise FetchError("Cross-origin write redirect refused")
                        # A third-party redirect must never inherit arbitrary
                        # client/vendor secret headers (e.g. X-Api-Key).
                        safe_headers = {"user-agent", "accept", "accept-language",
                                        "accept-encoding"}
                        headers = {k: v for k, v in headers.items()
                                   if k.lower() in safe_headers}
                    if response.status_code == 303 or (
                        response.status_code in {301, 302} and method.upper() == "POST"
                    ):
                        method = "GET"
                        arguments = {k: v for k, v in arguments.items()
                                     if k not in {"json", "data", "content", "files"}}
                    current = target
                    continue
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        raise FetchError("HTTP response too large")
                    chunks.append(chunk)
                return httpx.Response(
                    response.status_code, content=b"".join(chunks),
                    headers=response.headers, request=response.request,
                )
        raise FetchError("HTTP redirect limit exceeded")

    async def request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        try:
            validate_public_url(url, resolve_dns=not self._mock_transport)
        except UnsafeDestination as exc:
            raise FetchError(f"Unsafe outbound HTTP destination: {exc}") from exc
        parsed = urlsplit(url)
        host = parsed.netloc.lower()
        ua = random.choice(self.user_agents)
        base_headers = {
            "User-Agent": ua,
            "Referer": f"{parsed.scheme}://{parsed.netloc}/",
            **DEFAULT_BROWSER_HEADERS,
        }
        headers = {**base_headers, **kw.pop("headers", {})}
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            await self._polite_wait(host)
            try:
                resp = await self._safe_fetch(method, url, headers, **kw)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                log.debug("%s %s failed (%s), attempt %d", method, url, exc, attempt + 1)
            else:
                if resp.status_code not in RETRY_STATUS:
                    if resp.status_code >= 400:
                        raise FetchError(f"HTTP {resp.status_code} for {url}", status=resp.status_code)
                    return resp
                last_exc = FetchError(f"HTTP {resp.status_code} for {url}", status=resp.status_code)
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit() and attempt < self.max_retries:
                    await asyncio.sleep(min(int(retry_after), 120))
                    continue
            if attempt < self.max_retries:
                delay = self.backoff_base ** (attempt + 1) + random.uniform(0, 1)
                await asyncio.sleep(delay)
                headers["User-Agent"] = random.choice(self.user_agents)
        raise FetchError(str(last_exc) if last_exc else f"failed: {url}",
                         status=getattr(last_exc, "status", None))

    async def get_text(self, url: str, **kw: Any) -> str:
        return (await self.request("GET", url, **kw)).text

    async def get_json(self, url: str, **kw: Any) -> Any:
        return (await self.request("GET", url, **kw)).json()

    async def post_json(self, url: str, payload: Any, **kw: Any) -> Any:
        headers = {"Content-Type": "application/json", "Accept": "application/json", **kw.pop("headers", {})}
        return (await self.request("POST", url, json=payload, headers=headers, **kw)).json()
