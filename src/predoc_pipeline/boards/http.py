"""Shared async HTTP client: UA rotation, per-host politeness, retries with backoff."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

DEFAULT_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
]

RETRY_STATUS = {429, 500, 502, 503, 504, 520, 522, 524}


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
        self._host_interval: dict[str, float] = {}
        self._host_last: dict[str, float] = {}
        self._host_lock: dict[str, asyncio.Lock] = {}
        self._client = httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, transport=transport,
            headers={"Accept-Language": "en-GB,en;q=0.9", "Accept-Encoding": "gzip, deflate"},
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

    async def request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        host = urlsplit(url).netloc.lower()
        headers = {"User-Agent": random.choice(self.user_agents), **kw.pop("headers", {})}
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            await self._polite_wait(host)
            try:
                resp = await self._client.request(method, url, headers=headers, **kw)
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
                if retry_after.isdigit():
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
