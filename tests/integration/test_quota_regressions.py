"""Atomic per-attempt quota reservations and durable daily accounting."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from predoc_pipeline import state
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.ratelimit import QuotaExceeded, RateLimiter, quota_day
from predoc_pipeline.extract.gemini import ExtractionError, Extractor, _parse_retry_delay


@pytest.mark.parametrize("stored", [False, True])
def test_only_one_worker_can_reserve_last_daily_request(tmp_path, stored):
    path = tmp_path / "quota.db"
    init(path)
    with Database(path) as db:
        limiter = RateLimiter(requests_per_minute=600, requests_per_day=1,
                              safety_margin=1, store=db if stored else None)
        barrier = Barrier(8)

        def reserve(_):
            barrier.wait(timeout=3)
            try:
                limiter.acquire(day="2026-10-05")
                return True
            except QuotaExceeded:
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            assert sum(pool.map(reserve, range(8))) == 1
        assert limiter.remaining_today("2026-10-05") == 0


def test_independent_limiter_instances_share_atomic_database_budget(tmp_path):
    path = tmp_path / "quota.db"
    init(path)
    barrier = Barrier(2)

    def reserve(_):
        with Database(path) as db:
            limiter = RateLimiter(requests_per_minute=600, requests_per_day=1,
                                  safety_margin=1, store=db)
            barrier.wait(timeout=3)
            try:
                limiter.acquire(day="2026-10-05")
                return True
            except QuotaExceeded:
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(reserve, range(2))) == 1


def test_record_adds_outcome_without_spending_a_second_request(tmp_path):
    path = tmp_path / "quota.db"
    init(path)
    with Database(path) as db:
        limiter = RateLimiter(requests_per_minute=600, requests_per_day=1,
                              safety_margin=1, store=db)
        limiter.acquire(day="2026-10-05")
        limiter.record(day="2026-10-05", tokens=123, error=True)
        assert db.llm_usage("2026-10-05") == (1, 123)
        assert db.export_llm_usage()[0]["errors"] == 1


def test_local_budget_resets_for_a_new_quota_day():
    limiter = RateLimiter(requests_per_minute=600, requests_per_day=1, safety_margin=1)
    limiter.acquire(day="2026-10-05")
    assert limiter.remaining_today("2026-10-05") == 0
    assert limiter.remaining_today("2026-10-06") == 1
    limiter.acquire(day="2026-10-06")


def test_pacing_wait_across_midnight_checks_new_days_budget(monkeypatch):
    import predoc_pipeline.core.ratelimit as module

    limiter = RateLimiter(requests_per_minute=1, requests_per_day=1, safety_margin=1)
    limiter.acquire(day="2026-10-06")  # new day's last slot is already reserved
    days = iter(["2026-10-05", "2026-10-06"])
    monkeypatch.setattr(module, "quota_day", lambda: next(days))
    with pytest.raises(QuotaExceeded):
        limiter.acquire(sleep=lambda seconds: None)


@pytest.mark.parametrize("moment,expected", [
    (datetime(2027, 3, 14, 7, 30, tzinfo=UTC), "2027-03-13"),
    (datetime(2027, 3, 14, 10, 30, tzinfo=UTC), "2027-03-14"),
    (datetime(2027, 11, 7, 7, 30, tzinfo=UTC), "2027-11-07"),
    (datetime(2027, 11, 7, 9, 30, tzinfo=UTC), "2027-11-07"),
])
def test_quota_day_handles_actual_dst_transition_hours(moment, expected):
    assert quota_day(moment) == expected


def test_fresh_database_restores_daily_usage_and_replay_does_not_double_count(tmp_path):
    original = tmp_path / "original.db"
    fresh = tmp_path / "fresh.db"
    health = tmp_path / "health.json"
    init(original)
    init(fresh)
    with Database(original) as db:
        db.record_llm_call("2026-10-05", tokens=120, error=True)
        row = db.start_run("old")
        db.finish_run(row, {"outcome": "ok"}, {})
        state.export_health(db, health, stats={"outcome": "ok"})
    with Database(fresh) as db:
        db.start_run("new")
        state.restore_runs(db, health)
        assert db.llm_usage("2026-10-05") == (1, 120)
        state.restore_runs(db, health)
        assert db.llm_usage("2026-10-05") == (1, 120)
        limiter = RateLimiter(requests_per_minute=600, requests_per_day=1,
                              safety_margin=1, store=db)
        with pytest.raises(QuotaExceeded):
            limiter.acquire(day="2026-10-05")


@pytest.mark.parametrize("response", ["bad-json", "http-500", "transport", "bad-schema"])
def test_every_failed_outbound_attempt_is_counted(tmp_path, response):
    path = tmp_path / "quota.db"
    init(path)

    def handler(request):
        if response == "transport":
            raise httpx.ConnectError("unavailable", request=request)
        if response == "http-500":
            return httpx.Response(500)
        if response == "bad-schema":
            return httpx.Response(200, json={"output_text": "{}"})
        return httpx.Response(200, text="invalid json")

    with Database(path) as db, httpx.Client(transport=httpx.MockTransport(handler)) as client:
        limiter = RateLimiter(requests_per_minute=600, requests_per_day=10,
                              safety_margin=1, store=db)
        extractor = Extractor(api_key="test-key", model="test", base_url="https://example.org",
                              backend="interactions", limiter=limiter, client=client)
        with pytest.raises(ExtractionError):
            extractor.extract(text="Research job", source_url="https://example.org/job")
        assert db.llm_usage(quota_day())[0] == extractor.calls == 1
        assert db.export_llm_usage()[0]["errors"] == 1


@pytest.mark.parametrize("first_status", [404, 429])
def test_backend_and_key_retries_reserve_each_outbound_attempt(tmp_path, first_status):
    path = tmp_path / "quota.db"
    init(path)
    sent = []

    def handler(request):
        sent.append(request)
        if len(sent) == 1:
            return httpx.Response(first_status, headers={"retry-after": "0"})
        payload = {"is_vacancy": False, "rejection_reason": "not a vacancy", "confidence": 0.9}
        if str(request.url).endswith("/interactions"):
            return httpx.Response(200, json={"output_text": json.dumps(payload)})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"text": json.dumps(payload)}
        ]}}]})

    with Database(path) as db, httpx.Client(transport=httpx.MockTransport(handler)) as client:
        limiter = RateLimiter(requests_per_minute=600, requests_per_day=10,
                              safety_margin=1, store=db)
        extractor = Extractor(api_keys=["key-one", "key-two"], model="test",
                              base_url="https://example.org", limiter=limiter, client=client)
        assert not extractor.extract(text="Research job", source_url="https://example.org/job").is_vacancy
        assert len(sent) == extractor.calls == db.llm_usage(quota_day())[0] == 2
        assert db.export_llm_usage()[0]["errors"] == 1


def test_quota_blocks_retry_before_second_network_request(tmp_path):
    path = tmp_path / "quota.db"
    init(path)
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(404)

    with Database(path) as db, httpx.Client(transport=httpx.MockTransport(handler)) as client:
        limiter = RateLimiter(requests_per_minute=600, requests_per_day=1,
                              safety_margin=1, store=db)
        extractor = Extractor(api_key="test-key", model="test", base_url="https://example.org",
                              limiter=limiter, client=client)
        with pytest.raises(QuotaExceeded):
            extractor.extract(text="Research job", source_url="https://example.org/job")
        assert len(sent) == extractor.calls == db.llm_usage(quota_day())[0] == 1


@pytest.mark.parametrize("payload", [[], {"error": "busy"},
                                     {"error": {"details": "invalid"}},
                                     {"error": {"details": [None]}},
                                     {"error": {"details": [{"retryDelay": "nans"}]}}])
def test_malformed_429_metadata_cannot_break_quota_shutdown(payload):
    response = httpx.Response(429, json=payload, headers={"retry-after": "nan"})
    assert _parse_retry_delay(response) == 0.0


@pytest.mark.parametrize("record", [
    {"day": "2026-99-99", "requests": 1, "tokens": 0, "errors": 0},
    {"day": "2026-10-05", "requests": -1, "tokens": 0, "errors": 0},
    {"day": "2026-10-05", "requests": True, "tokens": 0, "errors": 0},
    {"day": "2026-10-05", "requests": 1},
])
def test_invalid_quota_records_roll_back_the_whole_import(tmp_path, record):
    path = tmp_path / "quota.db"
    init(path)
    with Database(path) as db:
        with pytest.raises(ValueError):
            db.import_llm_usage([
                {"day": "2026-10-04", "requests": 1, "tokens": 0, "errors": 0}, record,
            ])
        assert db.export_llm_usage() == []


@pytest.mark.parametrize("failed", [False, True, "invalid"])
def test_optional_sdk_uses_one_reserved_attempt_and_closes_client(tmp_path, monkeypatch, failed):
    from pydantic import ValidationError

    from predoc_pipeline.extract.instructor_backend import InstructorExtractor
    from predoc_pipeline.models import ExtractionResult

    sdk = Mock()
    patched = Mock()
    if failed == "invalid":
        patched.chat.completions.create.return_value = {"is_vacancy": "not a boolean"}
    elif failed:
        patched.chat.completions.create.side_effect = RuntimeError("provider failed")
    else:
        patched.chat.completions.create.return_value = ExtractionResult(is_vacancy=False)
    instructor = ModuleType("instructor")
    instructor.from_genai = Mock(return_value=patched)
    google = ModuleType("google")
    genai = ModuleType("google.genai")
    genai.Client = Mock(return_value=sdk)
    genai.types = SimpleNamespace(HttpOptions=SimpleNamespace, HttpRetryOptions=SimpleNamespace)
    google.genai = genai
    for name, module in (("instructor", instructor), ("google", google), ("google.genai", genai)):
        monkeypatch.setitem(sys.modules, name, module)
    path = tmp_path / "quota.db"
    init(path)
    with Database(path) as db:
        limiter = RateLimiter(requests_per_minute=600, requests_per_day=1,
                              safety_margin=1, store=db)
        with InstructorExtractor(api_key="test-key", model="test", limiter=limiter) as extractor:
            if failed == "invalid":
                with pytest.raises(ValidationError):
                    extractor.extract(text="Research job", source_url="https://example.org/job")
            elif failed:
                with pytest.raises(RuntimeError, match="provider failed"):
                    extractor.extract(text="Research job", source_url="https://example.org/job")
            else:
                extractor.extract(text="Research job", source_url="https://example.org/job")
            assert db.llm_usage(quota_day())[0] == extractor.calls == 1
            assert db.export_llm_usage()[0]["errors"] == int(bool(failed))
        retry = patched.chat.completions.create.call_args.kwargs["max_retries"]
        assert retry.stop.max_attempt_number == 1
        assert genai.Client.call_args.kwargs["http_options"].retry_options.attempts == 1
        sdk.close.assert_called_once()
