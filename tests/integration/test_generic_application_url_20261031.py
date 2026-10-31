"""A generic EURAXESS search page cannot serve as a vacancy application link."""
from __future__ import annotations

from predoc_pipeline import state
from predoc_pipeline.core.output_quality import application_url_issue


def test_euraxess_generic_search_is_not_individual_application():
    for url in (
        "https://euraxess.ec.europa.eu/jobs/search",
        "https://euraxess.ec.europa.eu/jobs/search?page=1",
        "https://www.euraxess.ec.europa.eu/jobs/search/",
    ):
        assert application_url_issue(url) == "generic-job-board-search"


def test_official_euraxess_vacancy_identity_remains_actionable():
    assert application_url_issue("https://euraxess.ec.europa.eu/jobs/476523") is None
    assert application_url_issue("https://jobs.example.org/jobs/search") is None


def test_dashboard_excludes_preexisting_generic_search_application_without_mutation():
    generic = {
        "url_hash": "a" * 64,
        "apply_url": "https://euraxess.ec.europa.eu/jobs/search",
        "source_url": "https://euraxess.ec.europa.eu/jobs/476523",
        "summary": "Actual postdoctoral research advertisement, but not an application URL.",
        "status": "published",
        "telegram_message_id": 54321,
    }
    direct = {
        **generic,
        "url_hash": "b" * 64,
        "apply_url": "https://euraxess.ec.europa.eu/jobs/476524",
        "source_url": "https://euraxess.ec.europa.eu/jobs/476524",
        "telegram_message_id": 54322,
    }

    class Database:
        def active_listings(self):
            return [generic, direct]

    visible = state._web_rows(Database(), set(), None)
    assert visible == [direct]
    assert generic["apply_url"] == "https://euraxess.ec.europa.eu/jobs/search"
    assert generic["telegram_message_id"] == 54321
