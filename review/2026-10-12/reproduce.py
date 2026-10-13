"""Offline review reproductions. All state is temporary; no real API calls."""

import json
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from unittest.mock import AsyncMock

import httpx

from predoc_pipeline import pipeline, state
from predoc_pipeline.boards.config import Preferences
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.urls import url_hash
from predoc_pipeline.ingest.collectors import collect_feeds
from predoc_pipeline.ingest.http import PoliteClient
from predoc_pipeline.models import RawItem
from predoc_pipeline.policy import Policy
from predoc_pipeline.publish.bot import telegram_sync
from predoc_pipeline.publish.telegram import TelegramClient, TelegramError
from predoc_pipeline.settings import Settings


def record(**extra):
    url = "https://example.org/job/one"
    return {
        "id": 42, "url_hash": url_hash(url), "title": "Research Assistant in Economics",
        "institution": "Example University", "source_url": url, "apply_url": url,
        "source": "test", "country": "United Kingdom", "is_remote": False,
        "first_seen_at": "2026-10-12T00:00:00Z", "last_seen_at": "2026-10-12T00:00:00Z",
        "summary": "Economics research and statistical analysis.", "language": "en",
        "visa_sponsorship_status": "unknown", "disciplines": ["economics"],
        "model_confidence": 0.9, "rule_score": 0.9, "confidence": 0.9,
        "status": "pending", **extra,
    }


def settings(root):
    return Settings(
        _env_file=None, db_path=str(root / "cache.db"), state_path=str(root / "listings.ndjson"),
        seen_state_path=str(root / "seen.ndjson"), dashboard_json=str(root / "listings.json"),
        health_json=str(root / "health.json"), feed_path=str(root / "feed.xml"),
        dlq_path=str(root / "dlq.json"), feedback_path=str(root / "feedback.json"),
        telegram_state_path=str(root / "telegram.json"),
        preferences_config=str(root / "preferences.toml"), sources_config=str(root / "sources.toml"),
        extraction_backend="heuristic", telegram_bot_token="offline-test-token",
        telegram_public_channel_id="123", x_broadcast_enabled=False,
        empty_run_alert_threshold=999,
    )


def stale_cache(root):
    s = settings(root)
    init(s.db_path)
    with Database(s.db_path) as db:
        db.import_rows([record()])
        newer = record(status="published", telegram_message_id=777,
                       published_at="2026-10-12T01:00:00Z")
        Path(s.state_path).write_text(json.dumps(newer), encoding="utf-8")
        state.restore_if_needed(db, s.state_path)
        result = {"status": db.listing(42)["status"],
                  "telegram_message_id": db.listing(42)["telegram_message_id"]}
        state.write_journal(db, s.state_path)
        result["rewritten_durable_status"] = state.read_journal(s.state_path)[0]["status"]
        assert result == {"status": "pending", "telegram_message_id": None,
                          "rewritten_durable_status": "pending"}
        return result


def pending_policy(root):
    s = settings(root)
    prefs = Preferences()
    prefs.enrich.fetch_details = False
    prefs.filters.excluded_employers = ["Example University"]
    init(s.db_path)
    with Database(s.db_path) as db:
        db.import_rows([record()])
        rejection = Policy(prefs).check_stored(db.listing(42))
        assert rejection
    calls = []

    def transport(request):
        calls.append(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 777}})

    with httpx.Client(transport=httpx.MockTransport(transport)) as client, \
            patch.object(pipeline, "load_preferences", return_value=prefs), \
            patch.object(pipeline, "load_sources", return_value=[]), \
            patch.object(pipeline, "gather", return_value=([], {})):
        stats = pipeline.run(s, sync_telegram=False, telegram_client=client)
    with Database(s.db_path) as db:
        final = db.listing(42)["status"]
    assert calls == ["sendMessage"] and final == "published"
    return {"current_policy_rejection": rejection, "remote_calls": calls,
            "published": stats.published, "final_status": final}


def exports_retry(root):
    s = settings(root)
    Path(s.telegram_state_path).write_text(json.dumps({"commands_version": "irrelevant",
                                                     "exports_pending": True}), encoding="utf-8")
    Path(s.state_path).write_text(json.dumps(record(status="published", country="United States")),
                                  encoding="utf-8")
    # A fresh runner has no SQLite cache. Normally the update branch initializes it.
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ok": True, "result": []}))) as client:
        result = telegram_sync(s, http_client=client, sleep=lambda _: None)
    assert result["failed"] == 0
    assert json.loads(Path(s.telegram_state_path).read_text())["exports_pending"] is False
    # Repeating the retry preserves the restored journal listing.
    init(s.db_path)
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ok": True, "result": []}))) as client:
        result2 = telegram_sync(s, http_client=client, sleep=lambda _: None)
    count = json.loads(Path(s.dashboard_json).read_text())["count"]
    assert count == 1 and result2["failed"] == 0
    return {"fresh_runner_failed": result["failed"], "empty_cache_export_count": count,
            "journal_listings": len(state.read_journal(s.state_path))}


def closed_hint(root):
    s = settings(root)
    init(s.db_path)
    with Database(s.db_path) as db:
        db.import_rows([record(status="published")])
        item = RawItem(source="test", source_url=record()["source_url"],
                       title=record()["title"], text="This position has been filled.",
                       hints={"board": True, "reject": "filled-or-closed"})
        assert pipeline._pre_extract(item, db=db, stats=pipeline.RunStats()) is None
        result = {"listing_status": db.listing(42)["status"],
                  "seen_decision": db.seen(url_hash(item.source_url))["decision"]}
        assert result == {"listing_status": "published", "seen_decision": "rejected"}
        return result


def uncertain_telegram():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("acknowledgement lost after server accepted", request=request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 778}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        tg = TelegramClient("offline-test-token", client=client)
        try:
            tg.send_message(chat_id="123", html="Example", sleep=lambda _: None)
        except TelegramError as error:
            assert error.uncertain and len(calls) == 1
        else:
            raise AssertionError("An uncertain submission must not be replayed")
    return {"identical_submission_attempts": len(calls), "fixed_in_synced_head": True}


def unchanged_feed(root):
    from predoc_pipeline.ingest.sources import Source

    init(root / "feed.db")
    xml = '<rss version="2.0"><channel><title>Jobs</title><item><title>Economics RA</title>' \
          '<link>https://example.org/job/one</link><description>Hiring economics researcher</description>' \
          '</item></channel></rss>'
    with Database(root / "feed.db") as db, \
            httpx.Client(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=xml))) as client:
        polite = PoliteClient("review", store=db, client=client, respect_robots=False,
                              per_host_delay=0)
        source = Source(name="fixture", kind="feed", url="https://example.org/feed", enabled=True)
        first, _ = collect_feeds([source], polite, max_items=10)
        second, stats = collect_feeds([source], polite, max_items=10)
        assert len(first) == 1 and len(second) == 1
        return {"first_poll_items": len(first), "retry_poll_items": len(second),
                "retry_errors": stats[0].errors, "fixed_in_synced_head": True}


def early_board_dedupe(root):
    from predoc_pipeline.boards import collector
    from predoc_pipeline.boards.config import SourceConfig
    from predoc_pipeline.boards.models import JobPostSchema
    from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper
    from datetime import date

    prefs = Preferences()
    prefs.enrich.fetch_details = False
    prefs.filters.strong_terms = ["predoc"]
    prefs.filters.field_terms = ["economics"]
    prefs.filters.allow_private_sector = True
    configs = [SourceConfig(name=n, type="link_scan", url="https://example.org/" + n)
               for n in ("one", "two")]
    posts = [JobPostSchema(title="Predoc in Economics", institution="Example University",
                           url="https://example.org/job/" + n, source=n,
                           deadline=date(2099, month, 1), pi_name=pi)
             for n, month, pi in (("one", 1, "Jane Doe"), ("two", 8, "Alan Smith"))]
    results = [collector.SourceResult(LinkScanScraper(c, None), [p])
               for c, p in zip(configs, posts, strict=True)]
    with patch.object(collector, "_scrape_all", new=AsyncMock(return_value=results)):
        result = asyncio.run(collector._collect(configs, prefs, lambda _: False, None))
    assert len(result.items) == 1
    return {"distinct_vacancies": len(posts), "emitted": len(result.items),
            "rejected": result.rejected}


def pagination_failure(root):
    from predoc_pipeline.boards.collector import SourceResult
    from predoc_pipeline.boards.config import SourceConfig
    from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper

    class FakeHttp:
        async def get_text(self, url):
            if "page=2" in url:
                raise RuntimeError("second page unavailable")
            return '<a href="/job/1">Research Assistant in Economics</a>'

    scraper = LinkScanScraper(SourceConfig(
        name="fixture", type="link_scan", url="https://example.org/jobs", max_pages=2,
        pagination_param="page", link_pattern="/job/"), FakeHttp())
    posts, _ = asyncio.run(scraper.run())
    stats = SourceResult(scraper, posts).as_stats()
    assert len(posts) == 1 and stats["ok"] and stats["errors"] == 0
    return {"posts": len(posts), "reported_ok": stats["ok"], "reported_errors": stats["errors"]}


def relaxed_policy_seen(root):
    s = settings(root)
    init(s.db_path)
    prefs = Preferences()
    prefs.filters.allow_private_sector = True
    item = RawItem(source="test", source_url=record()["source_url"],
                   title="Predoc in Economics", text="Hiring a predoc in economics.",
                   hints={"board": True})
    with Database(s.db_path) as db:
        stats = pipeline.RunStats()
        gate, key, digest = pipeline._pre_extract(item, db=db, stats=stats, policy=Policy(prefs))
        db.mark_seen(key, source=item.source, decision="rejected", reason="preferences:region-US",
                     content_hash=digest)
        prefs.filters.regions_include.append("US")
        assert pipeline._pre_extract(item, db=db, stats=stats, policy=Policy(prefs)) is None
        return {"prior_rejection": "preferences:region-US", "reconsidered_after_relaxation": False,
                "new_preferences_regions": prefs.filters.regions_include}


def main():
    results = {}
    with TemporaryDirectory(prefix="collegeum-review-") as directory:
        root = Path(directory)
        for name, function in (("stale_cache", stale_cache), ("pending_policy", pending_policy),
                               ("exports_retry", exports_retry), ("closed_hint", closed_hint),
                               ("unchanged_feed", unchanged_feed),
                               ("early_board_dedupe", early_board_dedupe),
                               ("pagination_failure", pagination_failure),
                               ("relaxed_policy_seen", relaxed_policy_seen)):
            folder = root / name
            folder.mkdir()
            results[name] = function(folder)
        results["uncertain_telegram"] = uncertain_telegram()
    print(json.dumps(results, indent=2))
    Path(__file__).with_name("reproduction-results-synced.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
