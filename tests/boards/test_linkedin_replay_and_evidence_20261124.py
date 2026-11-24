"""Offline follow-up contracts for LinkedIn evidence and bounded replay work."""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from predoc_pipeline.boards.config import EnrichConfig, SourceConfig
from predoc_pipeline.boards.heuristics import Enricher, apply_heuristics
from predoc_pipeline.boards.http import FetchError, HttpClient
from predoc_pipeline.boards.scrapers.linkedin_content import parse_detail_page, parse_search_page
from predoc_pipeline.boards.scrapers.linkedin_scheduler import QueryLedger, query_key
from predoc_pipeline.boards.scrapers.linkedin_scraper import LinkedInScraper

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
PAIR = ("PhD economics", "Germany")
JOB = "5000000000"
ROOT = Path(__file__).resolve().parents[2]


def cards(start=0, count=10):
    return [
        {"id": str(int(JOB) + start + i), "title": "PhD Economics", "company": "University"}
        for i in range(count)
    ]


def page(rows):
    return "".join(
        f'<div class="base-card" data-entity-urn="urn:li:jobPosting:{row["id"]}">'
        f'<a href="https://www.linkedin.com/jobs/view/{row["id"]}"></a>'
        f'<h3>{row["title"]}</h3><h4>{row["company"]}</h4></div>'
        for row in rows
    )


class OfflineHTTP:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def set_host_interval(self, *_args):
        pass

    async def get_text(self, url, **options):
        self.calls.append((url, options))
        await asyncio.sleep(0)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response(url) if callable(self.response) else self.response


def worker(http, *, path=None, **options):
    config = {
        "name": "linkedin", "type": "linkedin", "keywords": [PAIR[0]],
        "locations": [PAIR[1]], "query_budget": 1, "request_budget": 12,
        "max_pages": 12 if path else 2, "time_budget_seconds": 30,
        **options,
    }
    if path:
        config["checkpoint_path"] = str(path)
    result = LinkedInScraper(SourceConfig(**config), http)
    result._scheduler_now = lambda: NOW
    return result


def posting(scraper, ident=JOB):
    return scraper.make(
        title="PhD Economics", institution="Example University",
        url=f"https://www.linkedin.com/jobs/view/{ident}",
        extra={"linkedin_id": ident},
    )


@pytest.mark.parametrize("wrapper", [
    "aside", "nav", "footer", 'section class="related-jobs__description"',
    'section class="similar-jobs__section"', 'section class="recommended-jobs__panel"',
    'div class="base-card__metadata"',
])
def test_unrelated_descendants_cannot_supply_deadlines_eligibility_or_closed_status(wrapper):
    closing = wrapper.split()[0]
    html = (
        '<div class="show-more-less-html__markup">A doctoral research opportunity.'
        f'<{wrapper}>Other role: application deadline January 15, 2027. '
        f'PhD required. No longer accepting applications.</{closing}></div>'
    )
    detail = parse_detail_page(html, JOB)
    assert detail.status == "advert_body_received"
    assert detail.text == "A doctoral research opportunity."
    item = posting(worker(OfflineHTTP("")))
    apply_heuristics(item, detail.text)
    assert item.deadline is None
    assert not item.extra["phd_required"]
    assert not item.extra.get("closed")


def test_primary_nested_content_keeps_its_actual_restrictions():
    html = (
        '<div class="show-more-less-html__markup"><section class="base-cardinality">'
        '<p>Application deadline: January 15, 2027.</p><p>PhD required.</p>'
        '</section></div>'
    )
    detail = parse_detail_page(html, JOB)
    assert detail.status == "advert_body_received"
    assert detail.text == "Application deadline: January 15, 2027. PhD required."


@pytest.mark.parametrize("attributes", [
    "hidden", 'aria-hidden="true"', 'style="display: NONE"',
    'style="visibility: hidden"',
])
def test_hidden_ancestors_cannot_trigger_access_denial_or_supply_advert_text(attributes):
    hidden = (
        f'<section {attributes}><div class="authwall"><h1>Sign in required</h1></div>'
        '<div class="show-more-less-html__markup">Unrelated hidden advert.</div></section>'
    )
    primary = '<div class="show-more-less-html__markup">Actual advert.</div>'
    detail = parse_detail_page(hidden + primary, JOB)
    assert detail.status == "advert_body_received"
    assert detail.text == "Actual advert."
    search = parse_search_page(hidden + page(cards(count=1)))
    assert not search.access_challenge
    assert len(search.cards) == 1
    assert parse_detail_page(hidden, JOB).status == "missing_advert_body"


def test_hidden_nested_text_and_templates_do_not_pollute_primary_advert():
    html = (
        '<div class="show-more-less-html__markup">Actual advert.'
        '<div hidden><div>PhD required.</div></div>'
        '<template><section>Application deadline January 15, 2027.</section></template></div>'
    )
    assert parse_detail_page(html, JOB).text == "Actual advert."


def test_detail_size_limit_does_not_silently_drop_eligibility_evidence():
    complete = "x" * 20000
    assert parse_detail_page(f'<div class="description__text">{complete}</div>', JOB).text == complete
    oversized = '<div class="description__text">' + complete + ' PhD required.</div>'
    detail = parse_detail_page(oversized, JOB)
    assert detail.text is None
    assert detail.status == "advert_body_too_large"
    scraper = worker(OfflineHTTP(oversized))
    item = posting(scraper)
    verified = asyncio.run(Enricher(EnrichConfig()).enrich_many([(scraper, item)]))
    assert verified == set()
    assert item.extra["linkedin_detail_status"] == "advert_body_too_large"


def test_oversized_description_preserves_independent_primary_closure_evidence():
    oversized = '<div class="description__text">' + "x" * 20001 + '</div>'
    closure = '<p class="closed-job__flavor-text">No longer accepting applications</p>'
    detail = parse_detail_page(oversized + closure, JOB)
    assert detail.status == "advert_closed"
    assert detail.text == "No longer accepting applications"
    item = posting(worker(OfflineHTTP("")))
    apply_heuristics(item, detail.text)
    assert item.extra["closed"]
    assert item.deadline is None
    related = parse_detail_page(oversized + '<aside>' + closure + '</aside>', JOB)
    assert related.text is None and related.status == "advert_body_too_large"


def test_hidden_search_card_does_not_make_a_full_page_look_complete(tmp_path):
    html = page(cards(count=9)) + '<div hidden>' + page(cards(start=9, count=1)) + '</div>'
    parsed = parse_search_page(html)
    assert len(parsed.cards) == 9 and parsed.invalid_cards == 1
    path = tmp_path / "checkpoint.json"
    scraper = worker(OfflineHTTP(html), path=path)
    assert len(asyncio.run(scraper.run())[0]) == 9
    row = QueryLedger.load(path, "linkedin").state["queries"][query_key("linkedin", *PAIR)]
    assert row["pending"]["offset"] == 0
    assert row["last_complete_at"] is None


@pytest.mark.parametrize("corruption", [
    "query_keyword", "query_location", "card_id", "missing_title", "oversized_id",
    "query_provenance", "missing_observation", "invalid_detail_time",
])
def test_checkpoint_identity_and_provenance_corruption_fails_without_overwrite(tmp_path, corruption):
    ledger = QueryLedger("linkedin")
    ledger.request(PAIR, now=NOW)
    ledger.accept_page(PAIR, cards(count=1), now=NOW)
    state = deepcopy(ledger.state)
    row = state["queries"][query_key("linkedin", *PAIR)]
    entry = state["spool"][JOB]
    if corruption == "query_keyword":
        row["keyword"] = "unrelated search"
    elif corruption == "query_location":
        row["location"] = "unrelated location"
    elif corruption == "card_id":
        entry["card"]["id"] = "5999999999"
    elif corruption == "missing_title":
        del entry["card"]["title"]
    elif corruption == "oversized_id":
        oversized = "5" * 31
        entry["card"]["id"] = oversized
        state["spool"] = {oversized: entry}
    elif corruption == "query_provenance":
        entry["queries"] = [{"unrelated": "record"}]
    elif corruption == "missing_observation":
        del entry["observed_at"]
    elif corruption == "invalid_detail_time":
        entry["detail_last_attempt_at"] = "not a timestamp"
    path = tmp_path / "checkpoint.json"
    original = json.dumps(state)
    path.write_text(original)
    with pytest.raises(ValueError):
        QueryLedger.load(path, "linkedin")
    assert path.read_text() == original


def test_canonical_query_spelling_and_stored_checkpoints_remain_compatible():
    ledger = QueryLedger("linkedin")
    ledger.request(PAIR, now=NOW)
    row = ledger.state["queries"][query_key("linkedin", *PAIR)]
    row["keyword"] = "  PHD   ECONOMICS "
    row["location"] = " germany "
    assert QueryLedger("linkedin", state=ledger.state).request(PAIR, now=NOW).offset == 0
    for audience, source in (("econ", "linkedin"), ("life", "life_linkedin")):
        path = ROOT / f"data/linkedin_{audience}_search_state.json"
        original = path.read_bytes()
        restored = QueryLedger.load(path, source)
        assert restored.counts()["checkpointed_queries"] > 0
        assert path.read_bytes() == original


def test_repeated_page_survives_restart_without_cursor_advance_or_evidence_loss(tmp_path):
    ledger = QueryLedger("linkedin")
    ledger.request(PAIR, now=NOW)
    assert ledger.accept_page(PAIR, cards(), now=NOW) == "pending"
    path = tmp_path / "checkpoint.json"
    ledger.save(path)
    resumed = QueryLedger.load(path, "linkedin")
    later = NOW + timedelta(hours=1)
    assert resumed.request(PAIR, now=later).offset == 10
    repeated = [{**row, "company": "Updated university name"} for row in reversed(cards())]
    assert resumed.accept_page(PAIR, repeated, now=later) == "repeated_page"
    row = resumed.state["queries"][query_key("linkedin", *PAIR)]
    assert row["pending"]["offset"] == 10
    assert row["pending"]["pages"] == 1
    assert row["pending"]["last_page_at"] == NOW.isoformat()
    assert row["last_complete_at"] is None
    assert row["retry_after"] == (later + timedelta(hours=4)).isoformat()
    replay = resumed.items(now=later)
    assert {row["id"] for row in replay} == {row["id"] for row in cards()}
    assert all(row["company"] == "Updated university name" for row in replay)


def test_overlapping_but_distinct_pages_and_cross_query_duplicates_still_progress():
    ledger = QueryLedger("linkedin")
    ledger.request(PAIR, now=NOW)
    assert ledger.accept_page(PAIR, cards(), now=NOW) == "pending"
    ledger.request(PAIR, now=NOW)
    assert ledger.accept_page(PAIR, cards(start=1), now=NOW) == "pending"
    assert ledger.state["queries"][query_key("linkedin", *PAIR)]["pending"]["offset"] == 20
    other = ("doctoral research", "Germany")
    ledger.request(other, now=NOW)
    assert ledger.accept_page(other, cards(), now=NOW) == "pending"
    assert len(ledger.state["spool"][JOB]["queries"]) == 2


def test_partial_and_legacy_pages_do_not_fabricate_repeat_history():
    ledger = QueryLedger("linkedin")
    ledger.request(PAIR, now=NOW)
    assert ledger.accept_page(PAIR, cards(), now=NOW, parse_complete=False) == "partial"
    later = NOW + timedelta(hours=4)
    ledger.request(PAIR, now=later)
    assert ledger.accept_page(PAIR, cards(), now=later) == "pending"
    pending = ledger.state["queries"][query_key("linkedin", *PAIR)]["pending"]
    pending.pop("page_signatures")  # A checkpoint written before this change.
    legacy = QueryLedger("linkedin", state=ledger.state)
    legacy.request(PAIR, now=later)
    assert legacy.accept_page(PAIR, cards(start=10), now=later) == "pending"
    legacy.request(PAIR, now=later)
    assert legacy.accept_page(PAIR, cards(start=10), now=later) == "repeated_page"


def test_repeated_provider_pages_stop_after_two_requests_with_same_request_ceiling(tmp_path):
    path = tmp_path / "checkpoint.json"
    http = OfflineHTTP(page(cards()))
    scraper = worker(http, path=path)
    posts, _ = asyncio.run(scraper.run())
    assert len(http.calls) == 2
    assert scraper.search_diagnostics["request_budget"] == 12
    assert len(posts) == 10
    assert scraper.discovery_parse_errors
    ledger = QueryLedger.load(path, "linkedin")
    row = ledger.state["queries"][query_key("linkedin", *PAIR)]
    assert row["last_complete_at"] is None and row["pending"]["offset"] == 10
    deferred_http = OfflineHTTP(page(cards()))
    deferred = worker(deferred_http, path=path)
    deferred._scheduler_now = lambda: NOW + timedelta(hours=1)
    assert len(asyncio.run(deferred.run())[0]) == 10
    assert deferred_http.calls == []
    def resumed_response(url):
        offset = int(parse_qs(urlsplit(url).query)["start"][0])
        return page(cards(start=offset, count=10 if offset == 10 else 1))
    resumed_http = OfflineHTTP(resumed_response)
    resumed = worker(resumed_http, path=path)
    resumed._scheduler_now = lambda: NOW + timedelta(hours=4)
    assert len(asyncio.run(resumed.run())[0]) == 21
    assert len(resumed_http.calls) == 2
    assert resumed.search_diagnostics["completed_queries"] == 1


@pytest.mark.parametrize("checkpointed", [True, False])
def test_http_client_recognized_challenge_stops_all_remaining_queries(tmp_path, checkpointed):
    http = OfflineHTTP(FetchError("access_interstitial", status=200))
    path = tmp_path / "checkpoint.json" if checkpointed else None
    scraper = worker(http, path=path, keywords=[PAIR[0], "predoc economics", "economics RA"], query_budget=3)
    assert asyncio.run(scraper.run()) == ([], 0)
    assert len(http.calls) == 1
    assert scraper.search_diagnostics["access_limited"]
    assert asyncio.run(scraper.fetch_detail(posting(scraper))) is None
    assert len(http.calls) == 1
    if path:
        ledger = QueryLedger.load(path, "linkedin")
        assert ledger.state["access_blocked_until"] == (NOW + timedelta(hours=48)).isoformat()


def test_other_http_200_failure_does_not_invent_a_provider_access_block(tmp_path):
    path = tmp_path / "checkpoint.json"
    http = OfflineHTTP(FetchError("malformed response", status=200))
    scraper = worker(http, path=path, keywords=[PAIR[0], "predoc economics"], query_budget=2)
    asyncio.run(scraper.run())
    assert len(http.calls) == 2
    assert not scraper.search_diagnostics["access_limited"]
    ledger = QueryLedger.load(path, "linkedin")
    assert ledger.state["access_blocked_until"] is None
    assert all(row["retry_after"] == (NOW + timedelta(hours=4)).isoformat()
               for row in ledger.state["queries"].values())


def test_shared_http_client_200_gate_stops_queued_detail_requests(tmp_path):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, text="<h1>Bot verification required</h1>")
    async def run():
        async with HttpClient(
            transport=httpx.MockTransport(respond), default_min_interval=0, max_retries=3,
        ) as http:
            scraper = worker(http, path=tmp_path / "checkpoint.json")
            results = await asyncio.gather(
                *(scraper.fetch_detail(posting(scraper, str(int(JOB) + i))) for i in range(3)),
                return_exceptions=True,
            )
            assert isinstance(results[0], FetchError) and results[0].status == 200
            assert results[1:] == [None, None]
    asyncio.run(run())
    assert len(requests) == 1


def test_peer_access_denial_stops_an_already_queued_search_without_losing_first_page(tmp_path):
    peer_path = tmp_path / "life.json"
    def after_denial(_url):
        peer = QueryLedger("life_linkedin")
        peer.fail(("PhD biology", "Germany"), now=NOW, status=429)
        peer.save(peer_path)
        return page(cards(count=1))
    http = OfflineHTTP(after_denial)
    scraper = worker(
        http, path=tmp_path / "econ.json", keywords=[PAIR[0], "predoc economics"],
        query_budget=2, peer_checkpoint_path=str(peer_path), peer_checkpoint_source="life_linkedin",
    )
    posts, _ = asyncio.run(scraper.run())
    assert len(posts) == 1
    assert len(http.calls) == 1
    assert scraper.search_diagnostics["provider_cooldown_active"]
    assert scraper.discovery_limits
    assert scraper.search_diagnostics["unprocessed_selected"] == 1
