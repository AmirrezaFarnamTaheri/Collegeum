"""Additional offline audit evidence; uses only temporary files and mocked HTTP.

These assertions demonstrate current defects, rather than desired behavior.
Run from the repository root. No live publishing or network calls are made.
"""
from __future__ import annotations

import asyncio
import json
import math
import tomllib
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import httpx

from predoc_pipeline import state
from predoc_pipeline.boards.config import SourceConfig, load_preferences
from predoc_pipeline.boards.scrapers.university_ats import WorkdayScraper
from predoc_pipeline.boards.utils.dates import extract_deadline
from predoc_pipeline.core import gating
from predoc_pipeline.core.db import Database, init
from predoc_pipeline.core.textproc import telegram_visible_length
from predoc_pipeline.core.urls import content_hash
from predoc_pipeline.extract.heuristic import HeuristicExtractor
from predoc_pipeline.extract.prompt import SYSTEM_PROMPT
from predoc_pipeline.ingest.collectors import collect_feeds
from predoc_pipeline.ingest.http import PoliteClient
from predoc_pipeline.ingest.sources import Source
from predoc_pipeline.models import PredocListing
from predoc_pipeline.publish.feedback import FeedbackStore, load_state, save_state
from predoc_pipeline.publish.telegram import render_card, render_digest_pages
from predoc_pipeline.publish.x import XClient, XError


def listing(**changes: object) -> PredocListing:
    data: dict[str, object] = {
        "title": "Research Assistant", "institution": "Example University",
        "apply_url": "https://example.org/jobs/A", "source_url": "https://example.org/jobs/A",
    }
    data.update(changes)
    return PredocListing.model_validate(data)


def main() -> None:
    evidence: dict[str, object] = {}
    card = render_card(listing(salary_raw="<" * 6000))
    try:
        ET.fromstring("<root>" + card + "</root>")
    except ET.ParseError as exc:
        evidence["F39_card_budget_breaks_entities"] = str(exc)
    else:
        raise AssertionError("expected an entity cut by the raw HTML truncation")

    pages = render_digest_pages(
        [(str(i), listing(title="T" * 110, institution="I" * 90)) for i in range(30)],
        page_size=30,
    )
    size = telegram_visible_length(pages[0][0])
    assert size > 4096 and len(pages) == 1
    evidence["F40_digest_exceeds_message_limit"] = {"pages": len(pages), "characters": size}

    x = XClient()
    x.post_tweet = Mock(side_effect=["created-1", XError("second tweet failed")])
    try:
        x.post_thread(["first", "second"])
    except XError as exc:
        assert not hasattr(exc, "tweet_ids")
        evidence["F43_partial_thread_loses_created_id"] = {
            "calls": x.post_tweet.call_count, "recoverable_ids_on_error": False,
        }
    else:
        raise AssertionError("expected the second tweet to fail")

    records = [json.loads(line) for line in Path("data/listings.ndjson").read_text(
        encoding="utf-8"
    ).splitlines() if line.strip()]

    with TemporaryDirectory(prefix="collegeum-boundaries-") as directory:
        root = Path(directory)
        feedback_file = root / "feedback.json"
        feedback_file.write_text('{"marks":', encoding="utf-8")
        store = FeedbackStore(feedback_file)
        assert store.hidden == set()
        store.save()
        assert json.loads(feedback_file.read_text()) == {"marks": {}}
        cursor_file = root / "cursor.json"
        cursor_file.write_text('{"offset":', encoding="utf-8")
        assert load_state(cursor_file) == {}
        save_state(cursor_file, {})
        evidence["F44_corrupt_personal_state_overwritten"] = {
            "marks": json.loads(feedback_file.read_text()), "cursor": load_state(cursor_file),
        }

        feedback_file.write_text('{"marks": null}', encoding="utf-8")
        try:
            _ = FeedbackStore(feedback_file).hidden
        except AttributeError as exc:
            evidence["F44_valid_json_wrong_shape_crashes"] = str(exc)
        else:
            raise AssertionError("expected malformed marks structure to fail")

        journal = root / "listings.ndjson"
        row = dict(records[0], status="published", closed_at=None, expired_at=None,
                   deadline=None, summary="A control character: \x01", telegram_message_id=123)
        journal.write_text(json.dumps(row) + '\n{"broken":\n', encoding="utf-8")
        init(root / "journal.db")
        with Database(root / "journal.db") as db:
            assert state.restore_if_needed(db, journal) == 1
            state.write_journal(db, journal)
            assert len(journal.read_text().splitlines()) == 1
            evidence["F45_partial_restore_erases_bad_line"] = {
                "original_lines": 2, "rewritten_lines": 1,
            }
            feed = root / "feed.xml"
            assert state.export_feed(db, feed) == 1
            try:
                ET.parse(feed)
            except ET.ParseError as exc:
                evidence["F41_rss_forbidden_control_character"] = str(exc)
            else:
                raise AssertionError("expected invalid XML from an unfiltered control character")

        # No listings or seen verdicts are committed between the two collections.
        init(root / "cache.db")
        rss = (
            '<rss version="2.0"><channel><title>Jobs</title><item>'
            '<title>Research Assistant</title><link>https://example.org/jobs/A</link>'
            '<description>Full-time economics research position.</description>'
            '</item></channel></rss>'
        )
        responses = [rss, rss, rss.replace("/jobs/A", "/jobs/a")]

        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=responses.pop(0))

        with Database(root / "cache.db") as db, httpx.Client(
            transport=httpx.MockTransport(respond)
        ) as transport:
            polite = PoliteClient(user_agent="audit", client=transport, store=db,
                                  respect_robots=False, per_host_delay=0)
            sources = [Source("audit", "feed", "https://example.org/feed")]
            first, _ = collect_feeds(sources, polite, max_items=5)
            second, second_stats = collect_feeds(sources, polite, max_items=5)
            third, third_stats = collect_feeds(sources, polite, max_items=5)
            assert len(first) == 1 and second == [] and third == []
            assert db.counts()["listings"] == 0 and db.seen_count() == 0
            assert content_hash(rss) == content_hash(rss.replace("/jobs/A", "/jobs/a"))
            evidence["F46_unprocessed_feed_items_not_replayed"] = {
                "first_items": len(first), "retry_items": len(second),
                "retry_unchanged": second_stats[0].unchanged,
            }
            evidence["F47_case_sensitive_link_change_hidden"] = {
                "changed_items": len(third), "marked_unchanged": third_stats[0].unchanged,
            }

    # Mirrors the exporter expression exactly; benign arithmetic only, no execution.
    title = "=1+1"
    assert listing(title=title).title == title
    csv_cell = '"' + title.replace('"', '""') + '"'
    assert csv_cell == '"=1+1"'
    evidence["F42_formula_survives_csv_quoting"] = csv_cell

    prefs = tomllib.loads(Path("config/preferences.toml").read_text(encoding="utf-8"))
    registry = tomllib.loads(Path("config/sources.toml").read_text(encoding="utf-8"))
    enabled = sum(source.get("enabled", True) for source in registry["board"])
    concurrency = prefs["http"]["max_concurrent_sources"]
    timeout = prefs["http"]["source_timeout"]
    source_stage = math.ceil(enabled / concurrency) * timeout
    assert source_stage > 40 * 60
    evidence["F48_source_budget_exceeds_workflow_deadline"] = {
        "enabled": enabled, "concurrent": concurrency, "source_timeout_seconds": timeout,
        "source_stage_worst_case_seconds": source_stage, "workflow_timeout_seconds": 2400,
    }

    text = (
        "We are hiring a full-time research assistant for a funded PhD position in economics. "
        "Apply by 1 January 2027. Python experience required."
    )
    title = "PhD position in economics at Example University"
    gate = gating.evaluate(text, title=title, allow_phd=True, allow_postdoc=True)
    extractor = HeuristicExtractor(load_preferences("config/preferences.toml"))
    feed_result = extractor.extract(text=text, title=title, source_url="https://example.org/job")
    board_result = extractor.extract(text=text, title=title, source_url="https://example.org/job",
                                     hints={"board": True, "institution": "Example University"})
    assert gate.passed and not feed_result.is_vacancy and board_result.is_vacancy
    assert "Reject them." in SYSTEM_PROMPT and "outside the United States" in SYSTEM_PROMPT
    evidence["F49_policy_changes_not_propagated_to_extraction"] = {
        "gate_passed": gate.passed, "feed_extraction": feed_result.is_vacancy,
        "board_extraction": board_result.is_vacancy,
        "feed_rejection": feed_result.rejection_reason,
    }

    parsed, _ = extract_deadline("Application deadline (MM/DD/YYYY): 03/04/2027")
    assert parsed == date(2027, 4, 3)
    evidence["F50_explicit_month_first_deadline_ignored"] = {
        "expected": "2027-03-04", "parsed": str(parsed),
    }

    class WorkdayHTTP:
        calls = 0

        async def post_json(self, url: str, payload: dict[str, object]) -> dict[str, object]:
            self.calls += 1
            start = int(payload["offset"])
            return {
                "total": 61,
                "jobPostings": [
                    {"title": "Predoctoral Research Assistant", "externalPath": f"/job/{i}"}
                    for i in range(start, min(start + 20, 61))
                ],
            }

    workday_http = WorkdayHTTP()
    scraper = WorkdayScraper(
        SourceConfig(name="audit", type="workday",
                     url="https://example.wd1.myworkdayjobs.com/en-US/jobs"),
        workday_http,
    )
    posts, parsed_count = asyncio.run(scraper.run())
    assert len(posts) == 60 and workday_http.calls == 3 and parsed_count == 60
    evidence["F51_pagination_cap_has_no_partial_signal"] = {
        "advertised_total": 61, "returned": len(posts), "reported_count": parsed_count,
    }
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
