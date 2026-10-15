"""Security boundary tests for all outbound crawler HTTP clients.

Mock transports keep the suite fully offline and prove rejected destinations
never reach an HTTP transport (including redirect targets).
"""
from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from predoc_pipeline.boards.http import FetchError, HttpClient
from predoc_pipeline.core.network_safety import UnsafeDestination, validate_public_url
from predoc_pipeline.ingest.http import PoliteClient


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin",
    "http://[::1]/admin",
    "http://169.254.169.254/latest/meta-data",
    "https://10.2.3.4/secret",
    "https://172.16.0.2/secret",
    "https://192.168.1.1/",
    "https://0.0.0.0/",
    "https://2130706433/",
    "https://0177.0.0.1/",
    "https://0x7f000001/",
    "https://localhost/config",
    "https://db.internal/secrets",
    "https://service.local/admin",
    "https://user:password@example.org/jobs",
    "file:///etc/passwd",
    "http://example.org:0/jobs",
])
def test_url_validation_rejects_nonpublic_addresses(url):
    with pytest.raises(UnsafeDestination):
        validate_public_url(url, resolve_dns=False)


def test_url_validation_allows_public_websites_and_refuses_private_dns():
    assert validate_public_url("https://jobs.example.org/posting", resolve_dns=False)
    def public_dns(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.215.14", 443))]

    def private_dns(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 443))]
    assert validate_public_url("https://jobs.example.org/posting", resolver=public_dns)
    with pytest.raises(UnsafeDestination):
        validate_public_url("https://jobs.example.org/posting", resolver=private_dns)


def test_polite_client_blocks_local_redirect_without_following_it():
    visited = []

    def handler(request):
        visited.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/secrets"})

    with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        crawler = PoliteClient(user_agent="Collegeum test", client=client, respect_robots=False,
                               per_host_delay=0)
        result = crawler.get("https://example.org/jobs", sleep=lambda _: None)
    assert not result.ok
    assert len(visited) == 1
    assert "127.0.0.1" not in visited[0]


def test_polite_client_treats_denied_robots_as_blocked():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(403, text="Forbidden")
        return httpx.Response(200, text="Do not fetch")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        crawler = PoliteClient(user_agent="Collegeum test", client=client, respect_robots=True,
                               per_host_delay=0)
        response = crawler.get("https://example.org/jobs", sleep=lambda _: None)
    assert response.status == 999
    assert len(requested) == 1
    assert requested[0].endswith("/robots.txt")


def test_board_http_client_rejects_private_redirect_and_request():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(307, headers={"Location": "http://169.254.169.254/"})

    async def exercise():
        async with HttpClient(transport=httpx.MockTransport(handler),
                              max_retries=0, default_min_interval=0) as client:
            with pytest.raises(FetchError):
                await client.get_text("https://example.org/jobs")
            with pytest.raises(FetchError):
                await client.get_text("http://127.0.0.1/admin")
    asyncio.run(exercise())
    assert requested == ["https://example.org/jobs"]


def test_board_http_client_does_not_impersonate_search_referrals_after_403(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(403, text="Denied")

    async def no_delay(*_args):
        return None

    monkeypatch.setattr("predoc_pipeline.boards.http.asyncio.sleep", no_delay)

    async def exercise():
        async with HttpClient(transport=httpx.MockTransport(handler), max_retries=1,
                              default_min_interval=0) as client:
            with pytest.raises(FetchError):
                await client.get_text("https://example.org/jobs")
    asyncio.run(exercise())
    assert all("google.com" not in (req.headers.get("referer") or "") for req in requests)


def test_board_http_client_rejects_oversized_response():
    def handler(request):
        return httpx.Response(200, content=b"x" * (8 * 1024 * 1024 + 1))

    async def exercise():
        async with HttpClient(transport=httpx.MockTransport(handler), max_retries=0,
                              default_min_interval=0) as client:
            with pytest.raises(FetchError, match="too large"):
                await client.get_text("https://example.org/jobs")
    asyncio.run(exercise())
