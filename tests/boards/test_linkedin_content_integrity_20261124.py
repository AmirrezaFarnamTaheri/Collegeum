"""Offline LinkedIn identity, response-scope and provider-denial contracts."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from predoc_pipeline.boards.config import EnrichConfig, SourceConfig
from predoc_pipeline.boards.heuristics import Enricher
from predoc_pipeline.boards.http import FetchError
from predoc_pipeline.boards.scrapers.linkedin_content import (
    job_id_from_url,
    parse_detail_page,
    parse_search_page,
)
from predoc_pipeline.boards.scrapers.linkedin_scheduler import QueryLedger, query_key
from predoc_pipeline.boards.scrapers.linkedin_scraper import LinkedInScraper

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
JOB = "4980001999"
PAIR = ("PhD economics", "Germany")
BODY = '<div class="show-more-less-html__markup">Application deadline: January 15, 2027.</div>'


def card(ident=JOB, *, href=None, urn=None):
    href = href if href is not None else f"https://www.linkedin.com/jobs/view/{ident}"
    urn = urn if urn is not None else f"urn:li:jobPosting:{ident}"
    return (
        f'<div class="base-card" data-entity-urn="{urn}">'
        f'<a class="base-card__full-link" href="{href}"></a>'
        '<h3>PhD Economics</h3><h4>Example University</h4></div>'
    )


class OfflineHTTP:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def set_host_interval(self, *_args):
        return None

    async def get_text(self, url, **kwargs):
        self.calls.append((url, kwargs))
        await asyncio.sleep(0)  # Let simultaneous enrichers contend for the provider lock.
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def worker(http, *, path: Path | None = None, name="linkedin", **options):
    if path is not None:
        options["checkpoint_path"] = str(path)
    config = SourceConfig(
        name=name, type="linkedin", keywords=[PAIR[0]], locations=[PAIR[1]],
        query_budget=1, request_budget=1, max_pages=1, **options,
    )
    result = LinkedInScraper(config, http)
    result._scheduler_now = lambda: NOW
    return result


def post(scraper, ident=JOB):
    return scraper.make(
        title="PhD Economics", institution="Example University",
        url=f"https://www.linkedin.com/jobs/view/{ident}", extra={"linkedin_id": ident},
    )


@pytest.mark.parametrize("url", [
    "https://www.linkedin.com/jobs/view/4980001999",
    "https://uk.linkedin.com/jobs/view/phd-economics-4980001999?trackingId=abc",
    "/jobs/view/phd-economics-4980001999/",
])
def test_job_identity_accepts_actual_provider_paths(url):
    assert job_id_from_url(url) == JOB


@pytest.mark.parametrize("url", [
    "https://linkedin.com.evil.test/jobs/view/4980001999",
    "https://example.edu/jobs/view/4980001999",
    "https://example.edu/?url=https://linkedin.com/jobs/view/4980001999",
    "https://user@linkedin.com/jobs/view/4980001999",
    "https://linkedin.com:444/jobs/view/4980001999",
    "ftp://linkedin.com/jobs/view/4980001999",
    "https://linkedin.com/jobs/view/4980001999/another-job",
])
def test_unrelated_or_malformed_urls_cannot_manufacture_linkedin_identity(url):
    assert job_id_from_url(url) is None
    parsed = parse_search_page(card(href=url))
    assert parsed.cards == []
    assert parsed.invalid_cards == 1


def test_card_urn_and_link_must_agree_and_nested_markup_is_one_card():
    for html in (
        card(href="https://www.linkedin.com/jobs/view/4980002000"),
        card(urn="other:jobPosting:4980001999"),
    ):
        page = parse_search_page(html)
        assert not page.cards and page.invalid_cards == 1
    nested = '<div class="base-card">' + card() + '</div>'
    assert len(parse_search_page(nested).cards) == 1


def test_same_title_different_ids_remain_distinct_and_repeat_queries_keep_provenance():
    scraper = worker(OfflineHTTP(""))
    raw = parse_search_page(card() + card("4980002000")).cards
    raw[0]["_query"] = "PhD economics @ Germany"
    duplicate = {**raw[0], "_query": "doctoral researcher @ Germany"}
    posts = scraper.parse_postings([*raw, duplicate])
    assert len(posts) == 2
    assert posts[0].extra["queries"] == [
        "PhD economics @ Germany", "doctoral researcher @ Germany",
    ]


def test_detail_uses_primary_advert_and_its_explicit_closed_status_only():
    html = (
        '<link rel="canonical" href="https://www.linkedin.com/jobs/view/4980001999">'
        '<aside><div class="show-more-less-html__markup">Deadline January 1, 2027</div>'
        '<p class="closed-job__flavor-text">No longer accepting applications</p></aside>'
        + BODY
    )
    detail = parse_detail_page(html, JOB)
    assert detail.status == "advert_body_received"
    assert detail.text == "Application deadline: January 15, 2027."
    html += '<figcaption class="closed-job__flavor-text">No longer accepting applications</figcaption>'
    assert parse_detail_page(html, JOB).text.startswith("No longer accepting applications\n")


@pytest.mark.parametrize("wrapper_class", [
    "similar-jobs__section", "similar-jobs--expanded", "similar-jobs-list",
    "related-jobs__description", "recommended-jobs__panel", "base-card__metadata",
    "base-card--link",
])
def test_related_class_suffixes_cannot_supply_description_or_closed_evidence(wrapper_class):
    related = (
        f'<section class="{wrapper_class}">'
        '<div class="show-more-less-html__markup">Unrelated job description.</div>'
        '<p class="closed-job__flavor-text">No longer accepting applications</p></section>'
    )
    assert parse_detail_page(related, JOB).status == "missing_advert_body"
    detail = parse_detail_page(related + BODY, JOB)
    assert detail.status == "advert_body_received"
    assert detail.text == "Application deadline: January 15, 2027."


@pytest.mark.parametrize("wrapper_class", [
    "similar-jobsresearch", "related-jobsboard", "recommended-jobsboard",
    "base-cardinality", "primary-base-card__description",
])
def test_nonmatching_class_names_preserve_primary_advert(wrapper_class):
    detail = parse_detail_page(f'<section class="{wrapper_class}">{BODY}</section>', JOB)
    assert detail.status == "advert_body_received"
    assert detail.text == "Application deadline: January 15, 2027."


@pytest.mark.parametrize("html,status", [
    ('<h1>Jobs</h1><p>Application deadline: January 1, 2027.</p>', "missing_advert_body"),
    ('<aside>' + BODY + '</aside>', "missing_advert_body"),
    (BODY + '<div class="description__text">Unrelated text</div>'
     '<div class="show-more-less-html__markup">Another job</div>', "ambiguous_advert_body"),
    ('<link rel="canonical" href="https://linkedin.com/jobs/view/4980002000">'
     + BODY, "job_identity_mismatch"),
    ('<meta property="og:url" content="https://example.edu/jobs/view/4980001999">'
     + BODY, "job_identity_mismatch"),
])
def test_unscoped_or_conflicting_detail_is_not_evidence(html, status):
    parsed = parse_detail_page(html, JOB)
    assert parsed.text is None and parsed.status == status


def test_generic_page_cannot_enrich_a_deadline_or_report_a_successful_detail_fetch():
    scraper = worker(OfflineHTTP('<p>Application deadline: January 1, 2027.</p>'))
    candidate = post(scraper)
    enriched = asyncio.run(Enricher(EnrichConfig()).enrich_many([(scraper, candidate)]))
    assert enriched == set()
    assert candidate.deadline is None
    assert not candidate.extra.get("detail_text")
    assert candidate.extra["linkedin_detail_status"] == "missing_advert_body"


def test_real_advert_prose_about_sign_in_or_captcha_is_not_an_access_challenge():
    html = '<div class="description__text">Research CAPTCHA security. Sign in to apply.</div>'
    assert parse_detail_page(html, JOB).status == "advert_body_received"


def test_conflicting_requested_detail_identity_performs_no_http_call():
    http = OfflineHTTP(BODY)
    scraper = worker(http)
    candidate = post(scraper)
    candidate.extra["linkedin_id"] = "4980002000"
    assert asyncio.run(scraper.fetch_detail(candidate)) is None
    assert http.calls == []


def test_partial_card_page_preserves_readable_candidates_without_advancing_cursor(tmp_path):
    path = tmp_path / "linkedin.json"
    html = card() + card("4980002000", href="https://example.edu/jobs/view/4980002000")
    scraper = worker(OfflineHTTP(html), path=path)
    posts, count = asyncio.run(scraper.run())
    assert count == len(posts) == 1
    assert scraper.discovery_parse_errors
    assert scraper.search_diagnostics["completed_queries"] == 0
    ledger = QueryLedger.load(path, "linkedin")
    row = ledger.state["queries"][query_key("linkedin", *PAIR)]
    assert row["pending"]["offset"] == 0 and row["pending"]["pages"] == 0
    assert row["last_complete_at"] is None
    assert row["retry_after"] == (NOW + timedelta(hours=4)).isoformat()
    assert JOB in ledger.state["spool"]

    http = OfflineHTTP(card() + card("4980002000"))
    retry = worker(http, path=path)
    retry._scheduler_now = lambda: NOW + timedelta(hours=4)
    posts, count = asyncio.run(retry.run())
    assert count == len(posts) == 2
    assert parse_qs(urlsplit(http.calls[0][0]).query)["start"] == ["0"]
    assert retry.search_diagnostics["completed_queries"] == 1


def test_challenge_with_residual_cards_stops_discovery_and_checkpoints_denial(tmp_path):
    http = OfflineHTTP('<h1>Sign in to continue</h1>' + card())
    path = tmp_path / "linkedin.json"
    scraper = worker(http, path=path)
    assert asyncio.run(scraper.run()) == ([], 0)
    assert len(http.calls) == 1
    assert scraper.search_diagnostics["access_limited"] is True
    ledger = QueryLedger.load(path, "linkedin")
    assert ledger.state["access_blocked_until"] == (NOW + timedelta(hours=48)).isoformat()
    assert not ledger.state["spool"]


def test_legacy_guest_instance_does_not_restart_search_or_details_after_denial():
    http = OfflineHTTP(FetchError("HTTP 429", status=429))
    scraper = worker(http)
    assert asyncio.run(scraper.run()) == ([], 0)
    assert len(http.calls) == 1
    assert asyncio.run(scraper.fetch_detail(post(scraper))) is None
    assert asyncio.run(scraper.run()) == ([], 0)
    assert len(http.calls) == 1
    assert scraper.intentionally_deferred


@pytest.mark.parametrize("response", [
    FetchError("HTTP 403", status=403),
    FetchError("HTTP 429", status=429),
    FetchError("HTTP 999", status=999),
    '<h1>Sign in to continue</h1>' + BODY,
])
def test_detail_denial_stops_queued_requests_and_persists_peer_cooldown(tmp_path, response):
    path = tmp_path / "linkedin.json"
    http = OfflineHTTP(response)
    scraper = worker(http, path=path)
    candidates = [post(scraper, str(int(JOB) + index)) for index in range(3)]

    async def fetch_all():
        return await asyncio.gather(
            *(scraper.fetch_detail(item) for item in candidates), return_exceptions=True,
        )

    results = asyncio.run(fetch_all())
    assert isinstance(results[0], FetchError)
    assert results[1:] == [None, None]
    assert len(http.calls) == 1
    assert http.calls[0][1]["stop_on_429"] is True
    ledger = QueryLedger.load(path, "linkedin")
    assert ledger.state["access_blocked_until"] == (NOW + timedelta(hours=48)).isoformat()
    peer_http = OfflineHTTP(BODY)
    peer = worker(
        peer_http, path=tmp_path / "life.json", name="life_linkedin",
        peer_checkpoint_path=str(path), peer_checkpoint_source="linkedin",
    )
    assert asyncio.run(peer.fetch_detail(post(peer))) is None
    assert peer_http.calls == []


@pytest.mark.parametrize("backend", ["jobspy", "api", "guest-typo"])
def test_unsupported_backend_is_explicit_and_makes_no_requests(backend):
    http = OfflineHTTP(card())
    scraper = worker(http, backend=backend)
    with pytest.raises(ValueError, match="Unsupported LinkedIn backend"):
        asyncio.run(scraper.fetch_raw_postings())
    assert http.calls == []
    assert scraper.search_diagnostics["coverage"] == "unsupported"
    assert scraper.search_diagnostics["requests"] == 0
