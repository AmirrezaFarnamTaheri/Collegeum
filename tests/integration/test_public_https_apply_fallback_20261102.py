"""A real HTTP application gateway must remain browseable through its HTTPS advert."""
from __future__ import annotations

from predoc_pipeline import state

OFFICIAL_AD = (
    "https://www.jobs.ac.uk/job/DTI904/"
    "phd-studentshipuniversity-of-bristol-business-school-phd-bursaries"
)
INSECURE_APPLICATION = "http://www.bris.ac.uk/pg-howtoapply"


def test_specific_jobs_ac_uk_ad_is_safe_fallback_for_http_university_application() -> None:
    assert state._public_application_url(INSECURE_APPLICATION, OFFICIAL_AD) == OFFICIAL_AD


def test_generic_or_untrusted_source_does_not_rescue_an_insecure_apply_link() -> None:
    for bad in (
        "https://www.jobs.ac.uk/search/?keywords=phd",
        "https://www.jobs.ac.uk/job/",
        "http://www.jobs.ac.uk/job/DTI904/foo",
        "https://user:pass@www.jobs.ac.uk/job/DTI904/foo",
        "https://untrusted.example/job/DTI904/foo",
        None,
    ):
        assert state._public_application_url(INSECURE_APPLICATION, bad) is None


def test_secure_original_application_remains_preferred() -> None:
    apply_url = "https://bristol.ac.uk/apply/real-studentship/DTI904"
    assert state._public_application_url(apply_url, OFFICIAL_AD) == apply_url


def test_public_export_includes_only_safe_https_urls() -> None:
    class Database:
        def active_listings(self):
            return [
                {"url_hash": "a" * 64, "apply_url": INSECURE_APPLICATION,
                 "source_url": OFFICIAL_AD, "summary": "Official studentship advert"},
                {"url_hash": "b" * 64, "apply_url": INSECURE_APPLICATION,
                 "source_url": "https://www.jobs.ac.uk/search/", "summary": "Generic page"},
            ]
    assert [r["url_hash"] for r in state._web_rows(Database(), set(), None)] == ["a" * 64]
