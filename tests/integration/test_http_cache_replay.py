"""A conditional HTTP cache must not silently discard unprocessed adverts."""

import httpx

from predoc_pipeline.core.db import Database, init
from predoc_pipeline.ingest.http import PoliteClient


def test_replayed_304_includes_body_and_is_not_skipped(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, text="<p>Vacancy A</p>", headers={"etag": '"v1"'})
        assert request.headers.get("if-none-match") == '"v1"'
        return httpx.Response(304)

    path = tmp_path / "cache.sqlite3"
    init(path)
    with Database(path) as db, httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher = PoliteClient(user_agent="Collegeum", client=client, respect_robots=False)
        first = fetcher.get("https://example.org/jobs", sleep=lambda _: None)
        second = fetcher.get("https://example.org/jobs", sleep=lambda _: None)
        assert first.ok and not first.skipped
        assert second.ok and second.from_cache and not second.skipped
        assert second.text == first.text
        assert second.content == first.content
        assert len(requests) == 2


def test_equal_200_body_is_still_parseable(tmp_path):
    path = tmp_path / "cache.sqlite3"
    init(path)
    with Database(path) as db, httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, text="<p>Unprocessed vacancy</p>"
        ))
    ) as client:
        fetcher = PoliteClient(user_agent="Collegeum", client=client,
                               store=db, respect_robots=False)
        assert not fetcher.get("https://example.org/jobs", sleep=lambda _: None).skipped
        assert not fetcher.get("https://example.org/jobs", sleep=lambda _: None).skipped


def test_old_header_only_cache_never_sends_conditional_request(tmp_path):
    path = tmp_path / "cache.sqlite3"
    init(path)
    with Database(path) as db:
        db.http_cache_put("dummy", "https://example.org/jobs", etag='"v1"',
                          last_modified=None, body_hash="old", status=200)
        # The entry is intentionally stored under the real canonical URL key.
        from predoc_pipeline.core.urls import url_hash
        db.http_cache_put(url_hash("https://example.org/jobs"),
                          "https://example.org/jobs", etag='"v1"',
                          last_modified=None, body_hash="old", status=200)
        def handler(request):
            assert "if-none-match" not in request.headers
            return httpx.Response(200, text="New body")
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            fetcher = PoliteClient(user_agent="Collegeum", client=client,
                                   store=db, respect_robots=False)
            assert fetcher.get("https://example.org/jobs", sleep=lambda _: None).ok


def test_robots_policy_does_not_cross_origins():
    seen = []
    def handler(request):
        seen.append(str(request.url))
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n"
                                  if request.url.port == 8443 else
                                  "User-agent: *\nAllow: /")
        return httpx.Response(200, text="Vacancy")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetcher = PoliteClient(user_agent="Collegeum", client=client, respect_robots=True)
        blocked = fetcher.get("https://example.org:8443/private", sleep=lambda _: None)
        allowed = fetcher.get("https://example.org/private", sleep=lambda _: None)
        assert blocked.status == 999
        assert allowed.ok
        assert len([u for u in seen if u.endswith("/robots.txt")]) == 2
