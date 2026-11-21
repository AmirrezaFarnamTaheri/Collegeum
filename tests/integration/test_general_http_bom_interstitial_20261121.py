"""UTF-8 BOM-prefixed access challenges are still HTTP 200 interstitials."""

from __future__ import annotations

import httpx
import pytest

from predoc_pipeline.ingest.http import PoliteClient

URL = "https://example.edu/doctoral-vacancies"
BAD = "\ufeff<!doctype html><html><head><title>Just a moment...</title></head>" \
    "<body><h1>Funded PhD positions 2027</h1></body></html>"


class Cache:
    def __init__(self, body: bytes | None) -> None:
        self.body = body
        self.writes: list[object] = []

    def http_cache_get(self, _key: str):
        if self.body is None:
            return None
        return {"body": self.body, "etag": '"original"', "last_modified": None}

    def http_cache_put(self, *args: object, **kwargs: object) -> None:
        self.writes.append((args, kwargs))


@pytest.mark.parametrize("conditional", [False, True])
def test_bom_prefixed_html_challenge_is_rejected_before_cache_or_replay(
    conditional: bool,
) -> None:
    cache = Cache(BAD.encode("utf-8") if conditional else None)
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        assert ("if-none-match" in request.headers) is conditional
        if conditional:
            return httpx.Response(304)
        return httpx.Response(
            200, text=BAD, headers={"content-type": "text/html; charset=utf-8"},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = PoliteClient(
            user_agent="CollegeumTest/1.0",
            client=client,
            store=cache,
            respect_robots=False,
            per_host_delay=0,
        ).get(URL, sleep=lambda _: None)

    assert result.status == 0
    assert result.ok is False
    assert result.error.startswith("access_interstitial")
    assert cache.writes == []
    assert requests == [URL]


def test_bom_prefixed_real_vacancy_page_still_succeeds() -> None:
    legitimate = "\ufeff<html><title>Funded Economics PhD posts</title></html>"

    with httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, text=legitimate),
    )) as client:
        result = PoliteClient(
            user_agent="CollegeumTest/1.0",
            client=client,
            respect_robots=False,
            per_host_delay=0,
        ).get(URL, use_cache=False, sleep=lambda _: None)
    assert result.ok
    assert "Funded Economics PhD" in result.text
