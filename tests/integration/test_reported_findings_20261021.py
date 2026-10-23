"""Regressions for the findings reported on 2026-10-21, first and second pass.

The first pass covered three defects, each with the behaviour that was wrong
before the fix:

* a robots.txt refusal was reported as an *unchanged* source, so a source
  blocked for months never reached the failure streak or the maintainer alert;
* a duplicate posting URL could raise KeyError and fail a whole board;
* ``predoc-pipeline eval`` scored the strict feed path only, so the number
  quoted for the gate never described the job-board path used in production.

The second pass covers five more:

* ``config/sources.toml`` had duplicate ``enabled`` keys in two tables, which
  is a fatal TOML parse error -- every run aborted at source loading;
* a deadline written as ``Deadline: 15 March 2027`` was not parsed at all,
  so a real deadline was silently dropped;
* an RSS posting date was read with ``time.mktime()``, i.e. as local time,
  so an entry published late in the UTC day landed on the wrong calendar day
  on a runner that is not on UTC;
* ``OPENROUTER_API_KEYS=key1,key2`` could not be loaded at all, because
  pydantic-settings JSON-decodes list settings;
* stdlib ``logging`` records and structlog records were written in two
  different formats into the same CI log.

The third pass covers the stored-journal audit: a salary that was a calendar
year read as an amount had to be erasable, without a transient parse failure
erasing a salary that was correct.
"""

from __future__ import annotations

import calendar
import json
import logging
import time
import tomllib
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from predoc_pipeline.boards.collector import _is_duplicate_in_run
from predoc_pipeline.boards.filter import Verdict
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.core.gating import evaluate
from predoc_pipeline.core.health import source_status
from predoc_pipeline.ingest.collectors import collect_feeds, collect_portals
from predoc_pipeline.ingest.http import PoliteClient
from predoc_pipeline.ingest.sources import Source

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# The source registry must parse, and must not contain duplicate keys
# ---------------------------------------------------------------------------

def _board_table(path: Path, name: str) -> list[str]:
    """The lines of the ``[[board]]`` table that declares ``name``."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip().startswith("[["):
            blocks.append(current)
            current = []
        current.append(raw)
    blocks.append(current)
    for block in blocks:
        if any(line.strip() == f'name = "{name}"' for line in block):
            return block
    return []


def test_the_shipped_source_registry_parses():
    """A duplicate key in one table is a fatal TOML error, not a warning.

    ``tomllib`` refuses to parse such a file at all, so simply loading the
    registry is the regression guard for the defect this pass fixed.
    """
    path = ROOT / "config" / "sources.toml"
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    assert raw.get("board"), "the board registry must not be empty"


@pytest.mark.parametrize("name", ["trinity_cambridge_jobs", "bruegel_jobs"])
def test_a_board_table_declares_enabled_at_most_once(name):
    """The two boards that were switched off must not declare `enabled` twice."""
    block = _board_table(ROOT / "config" / "sources.toml", name)
    assert block, f"{name} is not in the registry"
    enabled = [line for line in block if line.strip().startswith("enabled")]
    assert len(enabled) <= 1, f"{name} declares `enabled` {len(enabled)} times: {enabled}"


def test_the_disabled_boards_stay_disabled():
    """The two boards that were disabled for HTTP 403 must not come back."""
    from predoc_pipeline.boards.config import load_board_sources

    sources = {s.name: s for s in load_board_sources(ROOT / "config" / "sources.toml")}
    assert not sources["trinity_cambridge_jobs"].enabled
    assert not sources["bruegel_jobs"].enabled


# ---------------------------------------------------------------------------
# A deadline written with a label is still a deadline
# ---------------------------------------------------------------------------

def test_a_label_prefixed_deadline_is_parsed():
    from predoc_pipeline.core.timeparse import parse_datetime

    parsed = parse_datetime("Deadline: 15 March 2027, 17:00")
    assert parsed is not None
    assert (parsed.year, parsed.month, parsed.day) == (2027, 3, 15)


def test_a_label_prefixed_deadline_with_trailing_garbage_is_rejected():
    from predoc_pipeline.core.timeparse import parse_datetime

    assert parse_datetime("Deadline: 2026-10-15junk") is None


# ---------------------------------------------------------------------------
# RSS posting dates are UTC dates
# ---------------------------------------------------------------------------

def _entry_with_date(stamp: time.struct_time) -> dict:
    return {"published_parsed": stamp}


def test_rss_entry_date_is_read_as_utc_not_local_time():
    """feedparser normalises `*_parsed` to UTC; mktime() would shift the day."""
    from predoc_pipeline.boards.scrapers.rss import _entry_date

    # 2026-10-20 23:30 UTC. On a UTC+3:30 runner this is already the 21st
    # locally; read as local time the date would come out one day early.
    stamp = time.struct_time((2026, 10, 20, 23, 30, 0, 0, 1, -1))
    assert _entry_date(_entry_with_date(stamp)) == date(2026, 10, 20)


def test_rss_entry_date_agrees_with_calendar_timegm():
    """The date must be the UTC calendar day, not the runner's local day."""
    from predoc_pipeline.boards.scrapers.rss import _entry_date

    stamp = time.struct_time((2026, 1, 1, 0, 30, 0, 0, 1, -1))
    expected = datetime.fromtimestamp(calendar.timegm(stamp), tz=UTC).date()
    assert _entry_date(_entry_with_date(stamp)) == expected


def test_rss_entry_date_does_not_follow_the_runner_timezone():
    """23:30 UTC is still the 20th, whatever the runner's local time is."""
    from predoc_pipeline.boards.scrapers.rss import _entry_date

    stamp = time.struct_time((2026, 10, 20, 23, 30, 0, 0, 1, -1))
    assert _entry_date(_entry_with_date(stamp)) == date(2026, 10, 20)
    # The UTC instant is the one the old code produced; only the conversion
    # back to a calendar date was wrong.
    assert calendar.timegm(stamp) == int(
        datetime(2026, 10, 20, 23, 30, tzinfo=UTC).timestamp()
    )


def test_rss_entry_date_without_a_struct_date_is_none():
    from predoc_pipeline.boards.scrapers.rss import _entry_date

    assert _entry_date({"published_parsed": None, "updated_parsed": None}) is None


# ---------------------------------------------------------------------------
# OpenRouter keys can be given as a plain comma-separated list
# ---------------------------------------------------------------------------

def test_comma_separated_openrouter_keys_are_loaded(monkeypatch):
    """A plain `key1,key2` used to raise a settings error at startup."""
    from predoc_pipeline.settings import Settings

    monkeypatch.setenv("OPENROUTER_API_KEYS", "key1,key2")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    settings = Settings(_env_file=None)
    assert settings.get_openrouter_keys() == ["key1", "key2"]


def test_openrouter_keys_accept_several_separators(monkeypatch):
    from predoc_pipeline.settings import Settings

    monkeypatch.setenv("OPENROUTER_API_KEYS", "key1; key2,key3")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    settings = Settings(_env_file=None)
    assert settings.get_openrouter_keys() == ["key1", "key2", "key3"]


def test_openrouter_keys_still_accept_a_json_list(monkeypatch):
    from predoc_pipeline.settings import Settings

    monkeypatch.setenv("OPENROUTER_API_KEYS", '["key1", "key2"]')
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    settings = Settings(_env_file=None)
    assert settings.get_openrouter_keys() == ["key1", "key2"]


def test_openrouter_keys_are_deduplicated_across_both_settings(monkeypatch):
    from predoc_pipeline.settings import Settings

    monkeypatch.setenv("OPENROUTER_API_KEYS", "key1,key2")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key2,key3")
    settings = Settings(_env_file=None)
    assert settings.get_openrouter_keys() == ["key1", "key2", "key3"]


def test_no_openrouter_keys_means_no_keys(monkeypatch):
    from predoc_pipeline.settings import Settings

    monkeypatch.setenv("OPENROUTER_API_KEYS", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    settings = Settings(_env_file=None)
    assert settings.get_openrouter_keys() == []


def test_a_comma_bearing_search_query_is_not_split(monkeypatch):
    """Only the key field is split; a query must keep its commas."""
    from predoc_pipeline.settings import Settings

    monkeypatch.setenv("TWITTER_SEARCH_QUERIES", '["econ, finance", "other"]')
    settings = Settings(_env_file=None)
    assert settings.twitter_search_queries == ["econ, finance", "other"]


# ---------------------------------------------------------------------------
# One log format for both logging worlds
# ---------------------------------------------------------------------------

def test_a_stdlib_record_renders_as_json_with_a_level_and_a_timestamp():
    """The stdlib path must produce the same shape as the structlog path."""
    from predoc_pipeline.logging_setup import render_record

    record = logging.LogRecord(
        name="predoc_pipeline.test", level=logging.INFO, pathname=__file__,
        lineno=1, msg="stdlib line %s", args=("here",), exc_info=None,
    )
    payload = json.loads(render_record(record))
    assert payload["event"] == "stdlib line here"
    assert payload["level"] == "info"
    assert payload["timestamp"].endswith("Z")


def test_stdlib_and_structlog_records_share_one_format(monkeypatch):
    """CI parses the run log; two formats in one file break that parser."""
    import io
    import sys

    import structlog

    from predoc_pipeline import logging_setup

    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    root = logging.getLogger()
    before = list(root.handlers)
    was_configured = logging_setup._CONFIGURED
    was_level = root.level
    # structlog's configuration is global; restore it so this test cannot
    # change the log format every other test sees.
    saved_structlog = structlog.get_config()
    for handler in list(root.handlers):
        if getattr(handler, "_predoc_rendered", False):
            root.removeHandler(handler)
    # configure() is idempotent by design; start from a clean slate here so the
    # check does not depend on whether another test configured it already.
    monkeypatch.setattr(logging_setup, "_CONFIGURED", False)
    try:
        logging_setup.configure()
        logging.getLogger("predoc_pipeline.test").info("stdlib line")
        logging_setup.get_logger("predoc_pipeline.test").info(
            "structlog line", extra_key="value"
        )
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
        root.handlers = before
        root.setLevel(was_level)
        monkeypatch.setattr(logging_setup, "_CONFIGURED", was_configured)
        structlog.configure(**saved_structlog)

    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    assert len(lines) == 2, stream.getvalue()
    payloads = [json.loads(line) for line in lines]
    assert {payload["event"] for payload in payloads} == {"stdlib line", "structlog line"}
    for payload in payloads:
        assert payload["level"] == "info"
        assert "timestamp" in payload


# ---------------------------------------------------------------------------
# A salary that is really a calendar year must be erasable
# ---------------------------------------------------------------------------

def test_a_stored_salary_that_is_a_calendar_year_is_cleared():
    """Listing 148 stored 2026.0 as a salary; the advert said "2026 rates"."""
    from predoc_pipeline.pipeline import _implausible_salary

    raw = "2026 rates, uplifted from April 2027 in line with inflation"
    assert _implausible_salary(2026.0, raw) is True
    assert _implausible_salary(2026.0, None) is False


def test_a_monthly_amount_that_looks_like_a_year_is_kept():
    """2000 per month is an amount, not the year 2000."""
    from predoc_pipeline.pipeline import _implausible_salary

    assert _implausible_salary(2000.0, "£2,000 per month") is False
    assert _implausible_salary(2000.0, "salary: 2000 per annum") is False


def test_a_real_salary_is_never_treated_as_implausible():
    from predoc_pipeline.pipeline import _implausible_salary

    assert _implausible_salary(75687.3, "75,687.30 to 93,671.30") is False
    assert _implausible_salary(25.55, "25.55 per hour") is False
    assert _implausible_salary(3400.0, "3400 per month") is False


def test_an_out_of_range_salary_is_implausible():
    from predoc_pipeline.pipeline import _implausible_salary

    assert _implausible_salary(-1.0, "negative") is True
    assert _implausible_salary(9_000_000.0, "too big") is True


def test_a_non_numeric_salary_is_not_implausible():
    from predoc_pipeline.pipeline import _implausible_salary

    assert _implausible_salary(None, "anything") is False
    assert _implausible_salary("2000", "2000") is False
    assert _implausible_salary(True, "true") is False


def test_the_journal_holds_no_year_shaped_salary():
    """The stored journal must not present a calendar year as an amount."""
    path = ROOT / "data" / "listings.ndjson"
    if not path.exists():
        pytest.skip("no journal in this checkout")
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        for column in ("salary_min", "salary_max"):
            value = record.get(column)
            if value is None:
                continue
            raw = record.get("salary_raw") or ""
            assert not _is_year_shaped_amount(value, raw), (
                f"listing {record.get('id')} stores {column}={value} "
                f"with salary_raw={raw!r}"
            )


def _is_year_shaped_amount(value: float, raw: str) -> bool:
    """A local copy of the year test, so the journal check needs no import."""
    import re

    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    number = int(float(value))
    if not 1900 <= number <= 2100 or float(value) != number:
        return False
    for match in re.finditer(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", raw):
        if int(match.group(1)) != number:
            continue
        if re.match(
            r"\s*(?:per|a\s+|/)\s*(?:month|monthly|year|annum|annually|hour|hourly|"
            r"day|daily|week|weekly)\b",
            raw[match.end():],
            re.IGNORECASE,
        ):
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# #4  A robots.txt refusal is a failure, not an unchanged source
# ---------------------------------------------------------------------------

def _robots_denying_client() -> httpx.Client:
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(403, text="Forbidden")
        return httpx.Response(200, text="Do not fetch")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_result_flags_a_robots_refusal_separately_from_unchanged():
    from predoc_pipeline.ingest.http import FetchResult

    blocked = FetchResult(url="https://example.org/jobs", status=999,
                          error="blocked by robots.txt")
    assert blocked.robots_blocked
    assert blocked.skipped  # it is still "skipped" for control flow

    unchanged = FetchResult(url="https://example.org/jobs", status=200, unchanged=True)
    assert not unchanged.robots_blocked
    assert unchanged.skipped

    ok = FetchResult(url="https://example.org/jobs", status=200, text="vacancy")
    assert not ok.robots_blocked
    assert not ok.skipped


def test_a_robots_blocked_feed_is_reported_as_failed_not_unchanged():
    with _robots_denying_client() as client:
        crawler = PoliteClient(user_agent="Collegeum test", client=client,
                               respect_robots=True, per_host_delay=0)
        source = Source(name="blocked-feed", kind="feed", url="https://example.org/feed.xml")
        items, stats = collect_feeds([source], crawler, max_items=10)

    assert items == []
    assert len(stats) == 1
    stat = stats[0]
    assert stat.unchanged == 0, "a blocked source must not look unchanged"
    assert stat.errors == 1
    assert any("robots" in message.lower() for message in stat.messages)
    # The run artifact must show this source as failed, so the failure streak
    # and the maintainer alert can see it.
    assert source_status(stat.as_dict()) == "failed"


def test_a_robots_blocked_portal_is_reported_as_failed_not_unchanged():
    with _robots_denying_client() as client:
        crawler = PoliteClient(user_agent="Collegeum test", client=client,
                               respect_robots=True, per_host_delay=0)
        source = Source(name="blocked-portal", kind="portal",
                        url="https://example.org/careers")
        items, stats = collect_portals([source], crawler, max_items=10)

    assert items == []
    stat = stats[0]
    assert stat.unchanged == 0
    assert stat.errors == 1
    assert source_status(stat.as_dict()) == "failed"


def test_a_genuinely_unchanged_source_is_still_reported_as_unchanged():
    """The fix must not turn every 304/unchanged source into a failure."""
    from predoc_pipeline.ingest.http import FetchResult

    unchanged = FetchResult(url="https://example.org/feed.xml", status=200, unchanged=True)
    stat_dict = {
        "items": 0, "fetched": 1, "unchanged": 1, "errors": 0, "messages": [],
    }
    assert source_status(stat_dict) == "successful"
    assert unchanged.unchanged


def test_a_robots_blocked_source_counts_towards_the_failure_streak():
    from predoc_pipeline.core.db import _source_failed

    blocked = {
        "items": 0, "fetched": 1, "unchanged": 0, "errors": 1,
        "messages": ["blocked by robots.txt"],
    }
    assert _source_failed(blocked) is True


def test_the_public_failure_message_for_a_robots_block_leaks_nothing():
    from predoc_pipeline.core.health import public_failure

    assert public_failure("blocked by robots.txt") == "Access restricted by robots policy"


# ---------------------------------------------------------------------------
# #5  A duplicate URL must not raise KeyError and fail a whole board
# ---------------------------------------------------------------------------

def _post(url: str, title: str = "Predoctoral Research Assistant") -> JobPostSchema:
    return JobPostSchema(
        title=title,
        url=url,
        source="test-board",
        institution="Test University",
        region="UK",
    )


def test_duplicate_url_whose_prior_candidate_is_gone_does_not_raise():
    """The reported crash: ``by_url`` outlived its candidate in ``candidates``."""
    candidates: dict = {}
    by_url = {"https://example.org/job": "stale-job-id"}

    post = _post("https://example.org/job")
    verdict = Verdict(keep=True, score=50)

    # Must not raise KeyError.
    assert _is_duplicate_in_run(candidates, by_url, post, verdict) is False


def test_duplicate_url_against_a_live_candidate_is_rejected():
    prior = _post("https://example.org/job")
    candidates = {prior.job_id: (None, prior, Verdict(keep=True, score=50))}
    by_url = {"https://example.org/job": prior.job_id}

    post = _post("https://example.org/job", title="Research Assistant (Predoc)")
    verdict = Verdict(keep=True, score=40)

    assert _is_duplicate_in_run(candidates, by_url, post, verdict) is True
    assert prior.job_id in candidates


def test_a_better_scoring_duplicate_replaces_the_earlier_candidate():
    prior = _post("https://example.org/job")
    candidates = {prior.job_id: (None, prior, Verdict(keep=True, score=40))}
    by_url = {"https://example.org/job": prior.job_id}

    post = _post("https://example.org/job", title="Research Assistant (Predoc)")
    verdict = Verdict(keep=True, score=80)

    assert _is_duplicate_in_run(candidates, by_url, post, verdict) is False
    assert prior.job_id not in candidates


def test_the_same_job_id_is_never_treated_as_its_own_duplicate():
    post = _post("https://example.org/job")
    candidates = {post.job_id: (None, post, Verdict(keep=True, score=50))}
    by_url = {"https://example.org/job": post.job_id}

    assert _is_duplicate_in_run(candidates, by_url, post, Verdict(keep=True, score=10)) is False


# ---------------------------------------------------------------------------
# #6  The eval harness must measure the path production actually uses
# ---------------------------------------------------------------------------

def test_the_board_path_awards_the_unconditional_score_floor():
    """known_vacancy=True skips the positive-signal checks and floors the rule score."""
    text = "PhD positions | Postdocs | Jobs"

    strict = evaluate(text, title="Research Assistant")
    board = evaluate(text, title="Research Assistant", known_vacancy=True)

    assert strict.score < board.score
    assert board.score == 0.55, "role-term 0.30 + hiring-intent 0.25 floor"


def test_the_board_path_still_applies_hard_rejects():
    text = "Postdoctoral Research Fellow in Econometrics. PhD required."
    result = evaluate(text, title="Postdoctoral Research Fellow", known_vacancy=True,
                      allow_postdoc=False)
    assert not result.passed


def test_allow_phd_overrides_the_phd_studentship_reject_on_the_board_path():
    title = "PhD Studentship in Economics"
    text = "Fully funded PhD studentship in economics at a research university."

    without = evaluate(text, title=title, known_vacancy=True)
    with_allow = evaluate(text, title=title, known_vacancy=True, allow_phd=True)

    assert not without.passed
    assert with_allow.passed


def test_eval_reports_which_paths_were_measured(tmp_path):
    """A fixture set with no board fixtures must not be quotable as a board score."""
    from typer.testing import CliRunner

    from predoc_pipeline.cli import app

    fixtures = tmp_path / "golden.jsonl"
    fixtures.write_text(
        json.dumps({
            "text": "The department is hiring a full-time research assistant in "
                    "economics. Applications are invited until 1 March 2027.",
            "title": "Research Assistant",
            "expect_pass": True,
        }) + "\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["eval", "--fixtures", str(fixtures)])
    assert result.exit_code == 0, result.output
    assert "paths measured: strict=1" in result.output
    assert "was NOT measured" in result.output


def test_eval_measures_the_board_path_when_a_fixture_declares_it(tmp_path):
    from typer.testing import CliRunner

    from predoc_pipeline.cli import app

    fixtures = tmp_path / "golden.jsonl"
    fixtures.write_text(
        json.dumps({
            "text": "PhD positions | Postdocs | Jobs",
            "title": "Research Assistant",
            "known_vacancy": True,
            "expect_pass": True,
        }) + "\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["eval", "--fixtures", str(fixtures)])
    assert result.exit_code == 0, result.output
    assert "paths measured: board=1" in result.output
    assert "not measured" not in result.output


def test_the_shipped_fixture_set_exercises_the_board_path():
    """The quoted gate score must cover the path that production uses."""
    from pathlib import Path

    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "golden.jsonl"
    if not fixtures.exists():  # pragma: no cover - depends on the working dir
        pytest.skip("fixture file not found")

    board = 0
    for line in fixtures.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if json.loads(line).get("known_vacancy"):
            board += 1
    assert board > 0, "the shipped fixture set must include board-path examples"
