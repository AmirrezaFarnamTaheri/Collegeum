"""Never cache or replay HTTP 200 anti-bot pages as genuine job listings."""
from __future__ import annotations

import httpx
import pytest

from predoc_pipeline.ingest.http import PoliteClient

URL = "https://example.edu/economics/phd-vacancies"
CHALLENGE = (
    "<html><head><title>Just a moment...</title></head>"
    "<body><p>Checking your browser before accessing this site</p>"
    "<h1>Funded Economics PhD vacancy</h1>"
    "<p>Applications close 11 December 2026.</p></body></html>"
)
CAPTCHA = (
    "<html><h1>Funded Economics PhD vacancy</h1>"
    '<form id="challenge-form"><div class="g-recaptcha"></div></form></html>'
)


class FakeCache:
    def __init__(self, body: bytes | None = None) -> None:
        self.body = body
        self.writes: list[object] = []

    def http_cache_get(self, _key):
        if self.body is None:
            return None
        return {
            "body": self.body, "etag": '"cached-etag"',
            "last_modified": None,
        }

    def http_cache_put(self, *args, **kwargs):
        self.writes.append((args, kwargs))


@pytest.mark.parametrize("page", [CHALLENGE, CAPTCHA])
def test_http200_antibot_html_is_not_a_successful_job_source(page):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(
            200, text=page,
            headers={"content-type": "text/html; charset=utf-8"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        crawler = PoliteClient(
            user_agent="CollegeumTest/1.0", client=http,
            respect_robots=False, per_host_delay=0,
        )
        result = crawler.get(URL, use_cache=False, sleep=lambda _: None)
    assert not result.ok
    assert result.status != 200
    assert "access_interstitial" in result.error
    assert seen == [URL]


def test_antibot_html_is_never_committed_to_advisory_cache():
    cache = FakeCache()

    def handler(_request):
        return httpx.Response(200, text=CAPTCHA, headers={"content-type": "text/html"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        crawler = PoliteClient(
            user_agent="CollegeumTest/1.0", client=http,
            store=cache, respect_robots=False, per_host_delay=0,
        )
        result = crawler.get(URL, sleep=lambda _: None)
    assert not result.ok
    assert cache.writes == []


def test_304_replay_of_historical_cached_antibot_html_is_not_a_success():
    cache = FakeCache(CHALLENGE.encode())

    def handler(request):
        assert request.headers["if-none-match"] == '"cached-etag"'
        return httpx.Response(304)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        crawler = PoliteClient(
            user_agent="CollegeumTest/1.0", client=http,
            store=cache, respect_robots=False, per_host_delay=0,
        )
        result = crawler.get(URL, sleep=lambda _: None)
    assert not result.ok
    assert result.status != 200
    assert "access_interstitial" in result.error
    assert cache.writes == []


def test_legitimate_university_login_link_and_304_cache_remain_allowed():
    legitimate = (
        "<html><nav><a href='/login'>Student login</a></nav>"
        "<h1>Funded Economics PhD vacancies</h1></html>"
    )
    for cached in (None, legitimate.encode()):
        cache = FakeCache(cached)

        def handler(_request, *, _cached=cached):
            if _cached is None:
                return httpx.Response(
                    200, text=legitimate, headers={"content-type": "text/html"},
                )
            return httpx.Response(304)

        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            crawler = PoliteClient(
                user_agent="CollegeumTest/1.0", client=http,
                store=cache, respect_robots=False, per_host_delay=0,
            )
            result = crawler.get(URL, sleep=lambda _: None)
        assert result.ok
        assert "Funded Economics PhD" in result.text
