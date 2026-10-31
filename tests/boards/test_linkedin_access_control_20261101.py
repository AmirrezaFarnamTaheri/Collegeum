"""Unauthorized/limited LinkedIn responses are not retried with new agents."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from predoc_pipeline.boards.http import FetchError, HttpClient

URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=phd"


@pytest.mark.parametrize("status", [403, 429])
def test_restricted_provider_response_stops_after_one_http_attempt(status: int) -> None:
    calls: list[int] = []

    def responder(_request: httpx.Request) -> httpx.Response:
        calls.append(status)
        return httpx.Response(status, headers={"Retry-After": "60"})

    async def run() -> None:
        async with HttpClient(
            max_retries=3, transport=httpx.MockTransport(responder),
        ) as client:
            with pytest.raises(FetchError) as error:
                await client.get_text(URL, stop_on_429=True)
            assert error.value.status == status

    asyncio.run(run())
    assert calls == [status]
