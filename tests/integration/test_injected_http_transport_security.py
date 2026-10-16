"""Security regressions for injected HTTP transports and robots parser failures.

A test-only MockTransport may skip DNS to keep unit tests offline; providing a
real transport/client must never silently disable public-destination DNS checks.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from predoc_pipeline.boards import http as board_http
from predoc_pipeline.core.network_safety import UnsafeDestination
from predoc_pipeline.ingest import http as ingest_http


def test_injected_real_sync_http_client_must_not_disable_dns_guard(monkeypatch):
    dns_validation = []

    def deny_for_test(_url: str, *, resolve_dns: bool):
        dns_validation.append(resolve_dns)
        raise UnsafeDestination("fixture rejects network access")

    monkeypatch.setattr(ingest_http, "validate_public_url", deny_for_test)
    with httpx.Client(transport=httpx.HTTPTransport()) as supplied:
        crawler = ingest_http.PoliteClient(
            user_agent="Collegeum tests", client=supplied, respect_robots=False,
            per_host_delay=0,
        )
        result = crawler.get("https://jobs.example.org/predoc", sleep=lambda _: None)

    assert result.error == "unsafe outbound HTTP destination"
    assert dns_validation and all(dns_validation)


def test_injected_real_async_http_transport_must_not_disable_dns_guard(monkeypatch):
    dns_validation = []

    def deny_for_test(_url: str, *, resolve_dns: bool):
        dns_validation.append(resolve_dns)
        raise UnsafeDestination("fixture rejects network access")

    monkeypatch.setattr(board_http, "validate_public_url", deny_for_test)

    async def run():
        async with board_http.HttpClient(
            transport=httpx.AsyncHTTPTransport(), max_retries=0,
            default_min_interval=0,
        ) as crawler:
            with pytest.raises(board_http.FetchError, match="Unsafe outbound"):
                await crawler.get_text("https://jobs.example.org/predoc")

    asyncio.run(run())
    assert dns_validation and all(dns_validation)


def test_broken_cached_robots_parser_must_fail_closed():
    class BrokenPolicy:
        def can_fetch(self, *_args):
            raise ValueError("malformed robots policy")

    with httpx.Client(transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, text="not reached")
    )) as supplied:
        crawler = ingest_http.PoliteClient(
            user_agent="Collegeum tests", client=supplied, respect_robots=True,
        )
        crawler._robots["https://jobs.example.org"] = BrokenPolicy()
        assert crawler.allowed("https://jobs.example.org/vacancies") is False


def test_mock_transports_still_work_without_real_dns(monkeypatch):
    checked = []

    def offline_guard(_url: str, *, resolve_dns: bool):
        checked.append(resolve_dns)
        return _url

    monkeypatch.setattr(ingest_http, "validate_public_url", offline_guard)
    with httpx.Client(transport=httpx.MockTransport(
        lambda _request: httpx.Response(200, text="Vacancy")
    )) as supplied:
        crawler = ingest_http.PoliteClient(
            user_agent="Collegeum tests", client=supplied, respect_robots=False,
            per_host_delay=0,
        )
        assert crawler.get("https://jobs.example.org/vacancies", sleep=lambda _: None).ok
    assert checked and not any(checked)
