"""Offline audit evidence. Run from the repository root; no remote requests.

These checks assert that the reported defects are reproducible in the audited
implementation. They are evidence checks, not the desired regression behavior.
All database work uses disposable temporary directories.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.dedupe import Deduplicator
from predoc_pipeline.core.ratelimit import RateLimiter
from predoc_pipeline.core.timeparse import days_between
from predoc_pipeline.core.urls import canonicalize_url
from predoc_pipeline.extract.heuristic import _extract_degree, _extract_tools
from predoc_pipeline.ingest.http import PoliteClient
from predoc_pipeline.models import PredocListing
from predoc_pipeline.publish.x import format_tweet, tweet_length


def main() -> None:
    evidence: dict[str, object] = {}
    records = [json.loads(line) for line in Path("data/listings.ndjson").read_text(
        encoding="utf-8"
    ).splitlines() if line.strip()]
    assert len(records) >= 2

    with TemporaryDirectory(prefix="collegeum-audit-") as directory:
        path = Path(directory) / "audit.db"
        init(path)
        with Database(path) as db:
            samples = [dict(records[0]), dict(records[1])]
            for sample, original_id in zip(samples, (7, 42), strict=True):
                sample.update(id=original_id, status="published", telegram_message_id=None,
                              closed_at=None, expired_at=None, deadline=None)
            db.import_rows(samples)
            rows = db.conn.execute("SELECT id FROM listings ORDER BY id")
            restored = [int(row["id"]) for row in rows]
            assert restored == [1, 2]
            evidence["F09_restore_ids"] = {"exported": [7, 42], "restored": restored}
            pending = db.pending_listings()
            assert len(pending) == 2 and all(r["status"] == "published" for r in pending)
            evidence["F01_published_web_rows_pending"] = len(pending)
            reported = db.import_rows(samples)
            actual = db.conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
            assert reported == 2 and actual == 2
            evidence["F20_duplicate_import_count"] = {
                "reported_inserted": reported, "actual_new": 0,
            }

    limiter = RateLimiter(requests_per_day=1, requests_per_minute=100, safety_margin=1)
    limiter.acquire()
    limiter.acquire()
    assert limiter.remaining_today() == 1
    evidence["F10_unreserved_daily_budget"] = {"allowed_before_record": 2, "budget": 1}

    degree = _extract_degree("Prepare for a PhD in economics. Bachelor's degree required.", {})
    tools = _extract_tools("C++ and Python are preferred, not required.", {})
    assert degree == "phd" and "C++" not in tools and "Python" in tools
    evidence["F14_contextual_degree_and_tools"] = {"degree": degree, "tools": tools}

    dedupe = Deduplicator()
    text = " ".join(f"shared-word-{i}" for i in range(60))
    dedupe.add(1, text=text, institution="Alpha University", title="Economics Research Assistant",
               deadline="2026-11-01")
    match = dedupe.find(
        text=text, institution="Beta University", title="Finance Research Assistant",
        deadline="2027-11-01",
    )
    assert match is not None and match.tier == "minhash"
    evidence["F21_distinct_employer_and_year_deduplicated"] = str(match)

    escaped = canonicalize_url("https://example.org/jobs/a%2Fb")
    separator = canonicalize_url("https://example.org/jobs/a/b")
    assert escaped == separator
    query_once = canonicalize_url("https://example.org/?id=%252F")
    query_twice = canonicalize_url("https://example.org/?id=%2F")
    assert query_once == query_twice
    evidence["F22_reserved_url_collisions"] = {"path": escaped, "query": query_once}

    earlier = datetime(2026, 1, 1, tzinfo=UTC)
    later = earlier + timedelta(hours=1)
    assert days_between(earlier, later) == 1 and days_between(later, earlier) == 0
    evidence["F23_asymmetric_day_gap"] = [
        days_between(earlier, later), days_between(later, earlier),
    ]

    listing = PredocListing(title="Research Assistant " * 12, institution="Institute " * 30,
                            apply_url="https://example.org/apply", source_url="https://example.org/ad")
    length = tweet_length(format_tweet(listing))
    assert length > 280
    evidence["F24_validated_tweet_exceeds_budget"] = length

    seen_requests: list[str] = []

    def robot_response(request: httpx.Request) -> httpx.Response:
        seen_requests.append(str(request.url))
        rules = (
            "User-agent: *\nDisallow: /jobs"
            if request.url.host == "www.example.org" else "User-agent: *\nAllow: /"
        )
        return httpx.Response(200, text=rules)

    with httpx.Client(transport=httpx.MockTransport(robot_response)) as client:
        polite = PoliteClient(user_agent="audit", client=client)
        first = polite.allowed("https://www.example.org/jobs")
        second = polite.allowed("https://example.org/jobs")
        assert not first and not second and len(seen_requests) == 1
        evidence["F25_robots_origin_collision"] = {
            "fetches": seen_requests, "second_origin_denied": not second,
        }

    from predoc_pipeline.cli import broadcast_pending
    try:
        broadcast_pending()
    except ImportError as error:
        assert "RunStats" in str(error)
        evidence["F08_broadcast_command"] = type(error).__name__ + ": " + str(error)
    else:
        raise AssertionError("Expected audited import failure")

    async def private_target_check() -> None:
        from predoc_pipeline.boards.http import HttpClient
        called: list[str] = []

        def response(request: httpx.Request) -> httpx.Response:
            called.append(str(request.url))
            return httpx.Response(200, text="mock only")

        async with HttpClient(
            transport=httpx.MockTransport(response), default_min_interval=0,
        ) as client:
            await client.get_text("http://127.0.0.1/private")
        assert called == ["http://127.0.0.1/private"]
        evidence["F26_private_fetch_guard_absent_mock_only"] = called

    asyncio.run(private_target_check())

    from datetime import date

    from predoc_pipeline.boards.config import Preferences
    from predoc_pipeline.boards.heuristics import detect_visa
    from predoc_pipeline.boards.utils.dates import extract_deadline
    from predoc_pipeline.extract.heuristic import visa_status

    deadline, _ = extract_deadline(
        "First review: October 1, 2026. Applications accepted until filled.",
        ref=date(2026, 10, 5),
    )
    assert deadline == date(2026, 10, 1)
    evidence["F34_rolling_first_review_becomes_deadline"] = str(deadline)
    note = detect_visa("International applicants are welcome. Relocation assistance provided.")
    assert visa_status(note) == "explicit"
    evidence["F36_welcome_becomes_explicit_visa"] = note

    from unittest.mock import patch

    from predoc_pipeline.boards.heuristics import apply_heuristics
    from predoc_pipeline.boards.models import JobPostSchema
    post = JobPostSchema(title="Economics Research Assistant", url="https://example.org/ad",
                         source="audit")
    with patch("predoc_pipeline.boards.utils.dates.today", return_value=date(2026, 10, 5)):
        apply_heuristics(post, "Expected start: July 2026. Start date is flexible. "
                              "Applications are open until filled.")
    assert "start date" in post.extra.get("closed", "")
    evidence["F35_flexible_start_becomes_closed"] = post.extra["closed"]

    from predoc_pipeline.core import fuzzy
    fast = fuzzy.ratio("abcd", "abxcd")
    with patch.object(fuzzy, "_rf", None):
        slow = fuzzy.ratio("abcd", "abxcd")
    assert fast > 88 and slow == 80
    evidence["F37_backend_dependent_similarity"] = {"rapidfuzz": fast, "stdlib": slow}

    async def zero_concurrency_check() -> None:
        from predoc_pipeline.boards.collector import _scrape_all
        prefs = Preferences.model_validate({"http": {"max_concurrent_sources": 0}})
        try:
            await asyncio.wait_for(
                _scrape_all([object()], prefs.http.max_concurrent_sources, .01), .05,
            )
        except TimeoutError:
            evidence["F33_zero_concurrency_accepted_and_hangs"] = True
        else:
            raise AssertionError("Expected semaphore wait")

    asyncio.run(zero_concurrency_check())

    from predoc_pipeline.extract.gemini import Extractor

    class Fallback:
        called = False

        def extract(self, **kwargs: object) -> object:
            self.called = True
            return object()

    fallback = Fallback()
    with (
        httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text="<html>not JSON</html>"),
        )) as client,
        Extractor(api_key="audit-dummy", model="audit", backend="openai",
                  base_url="https://example.org", client=client,
                  limiter=RateLimiter(), fallback_extractor=fallback) as extractor,
    ):
        try:
            extractor.extract(
                text="Economics research assistant", source_url="https://example.org/ad",
            )
        except json.JSONDecodeError:
            assert not fallback.called
            evidence["F30_non_json_200_skips_fallback"] = True
        else:
            raise AssertionError("Expected malformed response failure")

    from types import SimpleNamespace

    from predoc_pipeline.publish.bot import telegram_sync

    with TemporaryDirectory(prefix="collegeum-bot-audit-") as directory:
        root = Path(directory)
        settings = SimpleNamespace(
            telegram_bot_token="audit-dummy", owner_ids={123},
            preferences_config="config/preferences.toml", db_path=root / "bot.db",
            state_path=root / "missing.ndjson", telegram_state_path=root / "state.json",
            feedback_path=root / "feedback.json", site_url="https://example.org",
        )
        sends: list[str] = []

        def bot_response(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("getUpdates"):
                return httpx.Response(200, json={"ok": True, "result": [
                    {"update_id": 77, "message": {"chat": {"id": 123}, "text": "/positions"}}
                ]})
            if request.url.path.endswith("sendMessage"):
                sends.append("attempt")
                return httpx.Response(503, text="temporary outage")
            return httpx.Response(200, json={"ok": True, "result": True})

        with httpx.Client(transport=httpx.MockTransport(bot_response)) as client:
            telegram_sync(settings, http_client=client, sleep=lambda duration: None)
        cursor = json.loads(settings.telegram_state_path.read_text())["offset"]
        assert cursor == 78 and len(sends) == 4
        evidence["F27_failed_bot_reply_acknowledged"] = {
            "update_id": 77, "saved_offset": cursor, "failed_attempts": len(sends),
        }

    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
