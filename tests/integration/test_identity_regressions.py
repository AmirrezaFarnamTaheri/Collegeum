"""Semantic URL differences and duplicate identity compatibility."""

from datetime import UTC, datetime, timedelta

import pytest

from predoc_pipeline.boards.utils.text import canonical_url
from predoc_pipeline.core.dedupe import Deduplicator
from predoc_pipeline.core.timeparse import days_between
from predoc_pipeline.core.urls import canonicalize_url, clean_url, url_hash


@pytest.mark.parametrize("left,right", [
    ("/jobs/a%2Fb", "/jobs/a/b"),
    ("/job?id=%252F", "/job?id=%2F"),
    ("/job?position=1", "/job?position=2"),
    ("/job?cid=1", "/job?cid=2"),
    ("/job?sid=1", "/job?sid=2"),
    ("/job?ref=1", "/job?ref=2"),
    ("/job?source=1", "/job?source=2"),
    ("/job?src=1", "/job?src=2"),
    ("/job?id=1&id=2", "/job?id=2&id=1"),
    ("/job?id=%FF", "/job?id=%FE"),
    ("/#/jobs/1", "/#/jobs/2"),
    ("/#!/jobs/1", "/#!/jobs/2"),
])
def test_distinct_url_semantics_survive_both_normalizers(left, right):
    left, right = "https://example.org" + left, "https://example.org" + right
    assert url_hash(left) != url_hash(right)
    assert canonical_url(left) != canonical_url(right)


@pytest.mark.parametrize("url", [
    "https://example.org/a%2fb?id=%252F&x=%2b",
    "https://example.org/caf%C3%A9?q=caf%C3%A9",
    "https://example.org/a%2Db?utm_source=mail&id=3",
    "https://example.org/job?id=%FF",
    "https://example.org/#/jobs/1?position=3",
])
def test_canonicalization_is_idempotent(url):
    once = canonicalize_url(url)
    assert canonicalize_url(once) == once


def test_clickable_board_urls_preserve_www_and_varbi_path():
    assert canonical_url("https://www.cemfi.es/job?id=1") == (
        "https://www.cemfi.es/job?id=1"
    )
    url = "https://example.varbi.com/what:job/jobID:123"
    assert canonical_url(url) == clean_url(url) == url


def test_display_links_preserve_spa_routes_and_drop_ordinary_anchors():
    url = "https://example.org/#/jobs/123"
    assert clean_url(url) == url
    assert clean_url("https://example.org/job#top") == "https://example.org/job"


def test_linkedin_uses_terminal_job_id_and_validated_host():
    assert canonical_url("https://www.linkedin.com/jobs/view/20260000-role-4012345678") == (
        "https://www.linkedin.com/jobs/view/4012345678"
    )
    url = "https://linkedin.com.example.org/jobs/view/role-4012345678"
    assert canonical_url(url) == url


@pytest.mark.parametrize("hours", [1, 24, 335, 336, 337])
def test_deadline_distance_is_symmetric(hours):
    earlier = datetime(2027, 1, 1, tzinfo=UTC)
    later = earlier + timedelta(hours=hours)
    assert days_between(earlier, later) == days_between(later, earlier)
    assert days_between(earlier, later) == hours // 24


BODY = "We are hiring a research fellow to work on causal inference with administrative data. " * 8


@pytest.mark.parametrize("institution,title,pi,deadline", [
    ("Beta University", "Research Fellow", "Jane Doe", "2027-03-01"),
    ("Alpha University", "Software Engineer", "Jane Doe", "2027-03-01"),
    ("Alpha University", "Research Fellow", "John Smith", "2027-03-01"),
    ("Alpha University", "Research Fellow", "Jane Doe", "2028-03-01"),
])
def test_identical_boilerplate_cannot_merge_different_vacancies(institution, title, pi, deadline):
    dedup = Deduplicator()
    dedup.add(1, text=BODY, institution="Alpha University", title="Research Fellow",
              principal_investigator="Jane Doe", deadline="2027-03-01")
    assert dedup.find(text=BODY, institution=institution, title=title,
                      principal_investigator=pi, deadline=deadline) is None


def test_compatible_candidate_is_found_after_incompatible_best_text_match():
    dedup = Deduplicator()
    dedup.add(1, text=BODY, institution="Beta University", title="Research Fellow")
    dedup.add(2, text=BODY, institution="Alpha University", title="Research Fellow")
    hit = dedup.find(text=BODY, institution="Alpha University", title="Research Fellow")
    assert hit is not None and hit.listing_id == 2 and hit.tier == "minhash"


def test_syndicated_copy_with_abbreviated_pi_matches():
    dedup = Deduplicator()
    dedup.add(1, text=BODY, institution="Alpha University", title="Research Fellow",
              principal_investigator="Prof. Jane Doe", deadline="2027-03-01")
    hit = dedup.find(text=BODY, institution="Alpha University", title="Research Fellow",
                     principal_investigator="J. Doe", deadline="2027-03-05")
    assert hit is not None and hit.listing_id == 1
