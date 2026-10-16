"""Offline contract coverage for explicit X provider failover."""

from types import SimpleNamespace

import httpx

from predoc_pipeline.ingest.collectors import collect_twitter


def _settings():
    return SimpleNamespace(
        x_bearer_token="primary", xquik_api_key="backup",
        twitter_search_queries=["from:econ_RA -is:retweet"],
        twitter_search_accounts=["econ_RA"],
        max_items_per_source=50,
    )


def test_rate_limited_official_api_uses_xquik_without_erasing_diagnostics():
    requests = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, json={"detail": "rate limited"})
        return httpx.Response(200, json={"data": [
            {"id": "9001", "username": "econ_RA", "text": "Predoc in economics"}
        ]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        items, reports = collect_twitter(_settings(), client=client)
    assert len(requests) == 2
    assert len(items) == 1
    assert items[0].source == "xquik:@econ_RA"
    assert [report.name for report in reports] == ["x_api", "xquik"]
    assert any("rate limited" in msg for msg in reports[0].messages)


def test_official_permission_denial_does_not_trigger_quota_fallback():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(403, json={"detail": "permission denied"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        items, reports = collect_twitter(_settings(), client=client)
    assert not items
    assert len(calls) == 1
    assert [report.name for report in reports] == ["x_api"]


def test_explicit_quota_error_in_403_uses_backup():
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(403, json={"detail": "monthly quota exhausted"})
        return httpx.Response(200, json={"data": []})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        items, reports = collect_twitter(_settings(), client=client)
    assert not items
    assert len(calls) == 2
    assert [report.name for report in reports] == ["x_api", "xquik"]

def test_permission_error_mentioning_rate_limits_does_not_fall_back():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(403, json={"detail":
            "Permission denied: rate limit upgrades are not available."})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        items, reports = collect_twitter(_settings(), client=client)
    assert not items
    assert len(calls) == 1
    assert [report.name for report in reports] == ["x_api"]
