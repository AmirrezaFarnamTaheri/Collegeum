"""A generic EURAXESS search page cannot serve as a vacancy application link."""
from __future__ import annotations

from predoc_pipeline import state
from predoc_pipeline.core.output_quality import application_url_issue, excluded_by_audit


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


def test_reviewed_social_work_doctorate_stays_out_of_economics_publication():
    # University of Gothenburg req PAR 2026/834 is a doctorate in Social Work,
    # independently verified against its employer vacancy announcement.
    identity = "07c9e135ca70ad498084d2521ac6fcf1c1fd54deefd52a702e696fa13f8278ef"
    assert excluded_by_audit(identity)
    assert not excluded_by_audit("f" * 64)


def test_siepr_staff_directories_and_undergraduate_program_are_not_vacancies():
    # Employer pages verified: two are existing-people directories; the third
    # is an undergraduate-only program, not a post-baccalaureate RA vacancy.
    reviewed = (
        "3c0f5a1439671f2e2848d26aa519ac9a588e850b35dec70b7cc7dc85824f64a6",
        "c838a6d783151ffaa97aa1942caeeddee0a39d9554c3aea0dc19afc4c09d3ec7",
        "33eb1b1a810a3a66249a92008daab32a9b67b678f77d48e36db17c6761a932be",
    )
    assert all(excluded_by_audit(identity) for identity in reviewed)
