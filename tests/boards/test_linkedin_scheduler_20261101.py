"""Offline contracts for a durable, finite query-level LinkedIn schedule.

These tests intentionally fail against the slot-only PR #98 rotation.
They never make network calls or touch production journals.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from predoc_pipeline.boards.scrapers.linkedin_scheduler import (
    QueryLedger,
    lookback_window,
    query_key,
)

START = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
A = ("PhD in Economics", "Germany")
B = ("predoc economics", "Norway")
C = ("PhD epigenetics", "Switzerland")


def _card(ident: str) -> dict[str, str]:
    return {"id": ident, "title": "PhD in Economics", "company": "University"}


def test_stable_query_identity_is_scoped_and_canonical() -> None:
    assert query_key("econ", " PhD in Economics ", "Germany") == query_key(
        "econ", "phd  in economics", " germany",
    )
    assert query_key("life", *A) != query_key("econ", *A)
    assert query_key("econ", *B) != query_key("econ", *A)


def test_new_queries_are_prioritized_before_eligible_repeats_and_are_fair() -> None:
    ledger = QueryLedger("econ")
    pairs = [A, B, C]
    assert len(ledger.plan(pairs, now=START, limit=2)) == 2
    first = ledger.plan(pairs, now=START, limit=2)
    for pair in first:
        ledger.request(pair, now=START)
        ledger.accept_page(pair, [], now=START)
    next_pair = ledger.plan(pairs, now=START + timedelta(hours=4), limit=2)
    assert next_pair == [next(p for p in pairs if p not in first)]
    assert ledger.plan(pairs, now=START + timedelta(hours=36), limit=3) == [
        p for p in pairs if p not in first
    ]


def test_exact_query_two_day_cooldown_and_other_pairs_continue() -> None:
    ledger = QueryLedger("econ")
    ledger.request(A, now=START)
    ledger.accept_page(A, [], now=START)
    assert A not in ledger.plan([A, B], now=START + timedelta(hours=47), limit=2)
    assert B in ledger.plan([A, B], now=START + timedelta(hours=47), limit=2)
    assert A in ledger.plan([A], now=START + timedelta(hours=48), limit=1)


@pytest.mark.parametrize(("age_days", "expected"), [
    (2, 604800),
    (3, 604800),
    (8, 2592000),
    (20, 2592000),
])
def test_supported_windows_round_up_with_extra_day_overlap(
    age_days: int, expected: int,
) -> None:
    previous = START - timedelta(days=age_days)
    lookback, gap = lookback_window(previous, START)
    assert lookback == expected
    assert not gap


def test_first_discovery_uses_30_days_and_long_gap_is_reported() -> None:
    assert lookback_window(None, START) == (2592000, False)
    assert lookback_window(START - timedelta(days=45), START) == (
        2592000, True,
    )


def test_interrupted_page_retains_cursor_and_replays_candidates_next_run(tmp_path) -> None:
    path = tmp_path / "econ-search.json"
    ledger = QueryLedger.load(path, "econ")
    assert ledger.request(A, now=START).offset == 0
    page = [_card(str(4980000000 + i)) for i in range(10)]
    assert ledger.accept_page(A, page, now=START) == "pending"
    ledger.save(path)
    followup = QueryLedger.load(path, "econ")
    assert A in followup.plan([A, B], now=START + timedelta(hours=4), limit=2)
    assert followup.request(A, now=START + timedelta(hours=4)).offset == 10
    assert len(followup.items(now=START + timedelta(hours=4))) == 10
    assert followup.accept_page(A, [_card("4980000010")], now=START + timedelta(hours=4)) == "complete"
    assert A not in followup.plan([A], now=START + timedelta(hours=47), limit=1)
    followup.save(path)
    assert path.exists()


def test_stale_pagination_restarts_zero_without_dropping_replay(tmp_path) -> None:
    ledger = QueryLedger("econ")
    ledger.request(A, now=START)
    ledger.accept_page(A, [_card(str(4980000000 + i)) for i in range(10)], now=START)
    cursor = ledger.request(A, now=START + timedelta(hours=25))
    assert cursor.offset == 0
    assert len(ledger.items(now=START + timedelta(hours=25))) == 10


def test_failure_does_not_advance_full_checkpoint_and_has_retry_delay() -> None:
    ledger = QueryLedger("econ")
    ledger.request(A, now=START)
    ledger.fail(A, now=START, status=429)
    assert ledger.plan([A], now=START + timedelta(hours=4), limit=1) == []
    assert ledger.plan([A], now=START + timedelta(hours=48), limit=1) == [A]
    cursor = ledger.request(A, now=START + timedelta(hours=48))
    assert cursor.offset == 0
    assert not ledger.state["queries"][query_key("econ", *A)].get("last_complete_at")


def test_page_cap_is_labeled_truncated_not_complete() -> None:
    ledger = QueryLedger("econ")
    for i in range(2):
        ledger.request(A, now=START)
        outcome = ledger.accept_page(
            A, [_card(str(4980000000 + 10 * i + j)) for j in range(10)],
            now=START, max_pages=2,
        )
    assert outcome == "truncated"
    record = ledger.state["queries"][query_key("econ", *A)]
    assert record["status"] == "truncated"
    assert record["last_complete_at"] is None
    assert ledger.plan([A], now=START + timedelta(hours=1), limit=1) == []


def test_repeated_cards_merge_search_attribution_and_do_not_change_identity() -> None:
    ledger = QueryLedger("econ")
    ledger.request(A, now=START)
    ledger.accept_page(A, [_card("4980000000")], now=START)
    ledger.request(B, now=START)
    ledger.accept_page(B, [_card("4980000000")], now=START)
    cards = ledger.items(now=START + timedelta(hours=4))
    assert len(cards) == 1
    assert cards[0]["id"] == "4980000000"
    assert len(cards[0]["_queries"]) == 2


def test_state_is_atomic_and_source_isolation_is_enforced(tmp_path) -> None:
    path = tmp_path / "ledger.json"
    econ = QueryLedger("econ")
    econ.request(A, now=START)
    econ.accept_page(A, [_card("4980000000")], now=START)
    econ.save(path)
    assert QueryLedger.load(path, "econ").items(now=START)
    with pytest.raises(ValueError, match="source"):
        QueryLedger.load(path, "life")


@pytest.mark.parametrize("bad", ["{", "[]", '{"version":3}', '{"source":"econ","version":1,"queries":[],"spool":{}}'])
def test_corrupt_or_unrecognized_checkpoint_fails_closed(tmp_path, bad: str) -> None:
    path = tmp_path / "bad.json"
    path.write_text(bad)
    with pytest.raises(ValueError):
        QueryLedger.load(path, "econ")
    assert path.read_text() == bad


def test_full_replay_buffer_stops_before_advancing_cursor() -> None:
    ledger = QueryLedger("life", max_items=1)
    ledger.request(C, now=START)
    result = ledger.accept_page(C, [_card("4980000000"), _card("4980000001")], now=START)
    assert result == "backpressure"
    assert ledger.request(C, now=START).offset == 0
    assert ledger.items(now=START) == []


def test_empty_portfolio_no_work_and_out_of_order_clock_never_erases_state() -> None:
    ledger = QueryLedger("econ")
    assert ledger.plan([], now=START, limit=10) == []
    ledger.request(A, now=START)
    ledger.accept_page(A, [], now=START)
    assert ledger.plan([A], now=START - timedelta(days=1), limit=1) == []


def test_timestamps_and_replay_are_utc_serializable(tmp_path) -> None:
    ledger = QueryLedger("econ")
    ledger.request(B, now=START)
    ledger.accept_page(B, [_card("4980000011")], now=START)
    path = tmp_path / "state.json"
    ledger.save(path)
    parsed = json.loads(path.read_text())
    assert parsed["version"] == 1
    assert parsed["source"] == "econ"
    assert parsed["spool"]["4980000011"]["card"]["id"] == "4980000011"



def test_detail_attempt_fairness_is_durable_and_replayed(tmp_path) -> None:
    ledger = QueryLedger("life")
    ledger.request(C, now=START)
    ledger.accept_page(C, [_card("4980000000"), _card("4980000001")], now=START)
    assert all(not x["_detail_last_attempt_at"] for x in ledger.items(now=START))
    ledger.note_detail("4980000000", now=START)
    ledger.save(tmp_path / "life.json")
    restored = QueryLedger.load(tmp_path / "life.json", "life")
    attempted = next(x for x in restored.items(now=START) if x["id"] == "4980000000")
    unattempted = next(x for x in restored.items(now=START) if x["id"] == "4980000001")
    assert attempted["_detail_last_attempt_at"] == START.isoformat()
    assert unattempted["_detail_last_attempt_at"] is None



def test_bounded_replay_cycles_all_candidates_without_starving_old_items() -> None:
    ledger = QueryLedger("econ")
    ledger.request(A, now=START)
    ledger.accept_page(A, [_card(str(4980000000 + i)) for i in range(8)], now=START)
    seen: set[str] = set()
    for cycle in range(3):
        batch = ledger.items(
            now=START + timedelta(hours=cycle), limit=3,
        )
        assert len(batch) == 3
        seen |= {item["id"] for item in batch}
    # Once fewer than the batch size remain untouched, fill the spare slots
    # with oldest previously emitted records rather than shrinking the batch.
    assert len(seen) == 8


def test_replay_tracking_survives_restart_and_recovers_unprocessed(tmp_path) -> None:
    ledger = QueryLedger("life")
    ledger.request(C, now=START)
    ledger.accept_page(C, [_card(str(4980000000 + i)) for i in range(6)], now=START)
    first = {x["id"] for x in ledger.items(now=START, limit=2)}
    path = tmp_path / "queue.json"
    ledger.save(path)
    restored = QueryLedger.load(path, "life")
    later = {x["id"] for x in restored.items(now=START + timedelta(hours=4), limit=2)}
    assert first.isdisjoint(later)



def test_cooldown_begins_after_final_page_not_initial_scan_page() -> None:
    ledger = QueryLedger("econ")
    ledger.request(A, now=START)
    ledger.accept_page(
        A, [_card(str(4980000000 + i)) for i in range(10)], now=START,
    )
    later = START + timedelta(hours=4)
    ledger.request(A, now=later)
    ledger.accept_page(A, [], now=later)
    # The lookback coverage point remains START but the 48h cooldown
    # starts at the final page; do not repeat 44h after last query request.
    assert ledger.plan([A], now=START + timedelta(hours=48), limit=1) == []
    assert ledger.plan([A], now=START + timedelta(hours=52), limit=1) == [A]
    record = ledger.state["queries"][query_key("econ", *A)]
    assert record["last_complete_at"] == START.isoformat()
    assert record["last_completed_at"] == later.isoformat()



def test_seen_journal_acknowledgement_prunes_only_matching_candidate_ids() -> None:
    ledger = QueryLedger("econ")
    ledger.request(A, now=START)
    ledger.accept_page(A, [_card(str(4980000000 + i)) for i in range(3)], now=START)
    purged = ledger.prune_known(
        lambda url: url.endswith("/4980000000") or url.endswith("/4980000002")
    )
    assert purged == 2
    assert {x["id"] for x in ledger.items(now=START)} == {"4980000001"}
    assert ledger.counts()["acknowledged_seen"] == 2
    assert ledger.evict("4980000001") is True
    assert ledger.items(now=START) == []
    assert ledger.counts()["acknowledged_filtered"] == 1


def test_seen_pruning_never_loses_cards_when_predicate_raises() -> None:
    ledger = QueryLedger("econ")
    ledger.request(A, now=START)
    ledger.accept_page(A, [_card("4980000000")], now=START)
    def broken(_url: str) -> bool:
        raise OSError("journal unavailable")
    with pytest.raises(OSError):
        ledger.prune_known(broken)
    assert [x["id"] for x in ledger.items(now=START)] == ["4980000000"]



def test_duplicate_page_does_not_reset_replay_and_detail_attempt_history() -> None:
    """Cross-search duplicates must not monopolize the small detail quota."""
    ledger = QueryLedger("life")
    ledger.request(C, now=START)
    ledger.accept_page(C, [_card("4980000000")], now=START)
    ledger.note_detail("4980000000", now=START)
    first = ledger.items(now=START, limit=1)
    assert first[0]["_detail_last_attempt_at"] == START.isoformat()
    later = START + timedelta(hours=4)
    ledger.request(A, now=later)
    ledger.accept_page(A, [_card("4980000000")], now=later)
    row = ledger.state["spool"]["4980000000"]
    assert row["observed_at"] == START.isoformat()
    assert row["detail_last_attempt_at"] == START.isoformat()
    assert row["last_replayed_at"] == START.isoformat()
    assert len(row["queries"]) == 2


def test_provider_429_pauses_entire_source_across_checkpoint_restarts(tmp_path) -> None:
    """A provider limit is global to the source, not to one query's keyword."""
    ledger = QueryLedger("econ")
    ledger.request(A, now=START)
    ledger.fail(A, now=START, status=429)
    assert ledger.plan([B, C], now=START + timedelta(hours=4), limit=2) == []
    path = tmp_path / "ratelimited.json"
    ledger.save(path)
    resumed = QueryLedger.load(path, "econ")
    assert resumed.plan([B], now=START + timedelta(hours=47), limit=1) == []
    assert resumed.plan([B], now=START + timedelta(hours=48), limit=1) == [B]


def test_provider_403_also_blocks_distinct_queries_and_next_run(tmp_path) -> None:
    ledger = QueryLedger("life")
    ledger.request(C, now=START)
    ledger.fail(C, now=START, status=403)
    ledger.save(tmp_path / "blocked.json")
    restored = QueryLedger.load(tmp_path / "blocked.json", "life")
    assert restored.plan([A, B], now=START + timedelta(hours=8), limit=2) == []
    assert set(restored.plan([A, B], now=START + timedelta(hours=48), limit=2)) == {A, B}
