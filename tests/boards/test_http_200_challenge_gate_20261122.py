"""HTTP 200 browser checks must not be parsed as real board vacancy pages."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from predoc_pipeline.boards.http import FetchError, HttpClient

URL = "https://university.example.edu/jobs"


@pytest.mark.parametrize(
    "body",
    [
        (
            "<!doctype html><html><title>Just a moment...</title>"
            "<body>Fully funded PhD Economics 2027, apply today</body></html>"
        ),
        (
            "\ufeff<html><head><title>Jobs</title></head>"
            "<h1>Access denied</h1><h2>PhD Researcher</h2></html>"
        ),
        (
            "<html><body><form id='challenge-form'>"
            "Apply for funded economics PhD posts</form></body></html>"
        ),
        (
            "<html><body><div class='g-recaptcha'>"
            "Economics Research Assistant</div></body></html>"
        ),
    ],
)
def test_browser_check_http_200_is_rejected_without_retry_or_ingestion(body: str) -> None:
    calls: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200, text=body, headers={"content-type": "text/html; charset=utf-8"},
        )

    async def run() -> None:
        async with HttpClient(
            transport=httpx.MockTransport(responder),
            max_retries=3,
            default_min_interval=0,
        ) as client:
            with pytest.raises(FetchError, match="access_interstitial") as error:
                await client.get_text(URL)
            assert error.value.status == 200

    asyncio.run(run())
    assert calls == [URL]


@pytest.mark.parametrize(
    "content_type,body",
    [
        (
            "text/html",
            "<html><head><title>Economics jobs</title></head>"
            "<h1>Funded PhD research programme</h1>"
            "<p>Just a moment while we introduce the project.</p></html>",
        ),
        (
            "application/json",
            '{"title":"Just a moment of econometric inspiration",'
            '"role":"Research Assistant"}',
        ),
    ],
)
def test_legitimate_200_html_or_json_stays_available(
    content_type: str, body: str,
) -> None:
    calls: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=body, headers={"content-type": content_type})

    async def run() -> None:
        async with HttpClient(
            transport=httpx.MockTransport(responder),
            max_retries=0,
            default_min_interval=0,
        ) as client:
            assert await client.get_text(URL) == body

    asyncio.run(run())
    assert calls == [URL]
