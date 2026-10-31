"""Dual PhD/postdoc adverts may offer a real, distinct master's-entry PhD route."""
from __future__ import annotations

from datetime import date

from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.ingest import life_sciences


def _post(*, title="PhD/Postdoc in In Vivo CRISPR Screening",
          description="A Master's degree for PhD applicants or a PhD for "
          "postdoctoral applicants in molecular biology.",
          deadline=date(2026, 11, 30)):
    return JobPostSchema(
        title=title,
        source="life_vib",
        url="https://jobs.vib.be/j/137660/phdpostdoc-in-vivo-crispr-screening",
        institution="VIB",
        country="Belgium",
        location="Ghent, Belgium",
        description_snippet=description,
        deadline=deadline,
    )


def test_dual_role_requires_detail_enrichment_despite_known_field_and_country():
    advert = _post()
    advert.description_snippet = "CRISPR screening and single-cell biology."
    advert.deadline = None
    assert life_sciences._needs_detail(advert)


def test_explicit_masters_entry_phd_with_future_deadline_is_eligible():
    advert = _post()
    accepted = life_sciences.classify_post(advert, today=date(2026, 10, 31))
    assert accepted is not None
    assert accepted["category"] == "life_sciences_phd"
    assert accepted["country"] == "Belgium"
    assert accepted["deadline"] == "2026-11-30"
    assert accepted["funding_status"] == "unverified"


def test_dual_role_without_explicit_phd_entry_requirement_fails_closed():
    advert = _post(description="Postdoctoral applicants must have a PhD in biology.")
    assert life_sciences.classify_post(advert, today=date(2026, 10, 31)) is None


def test_dual_role_without_deadline_fails_closed():
    assert life_sciences.classify_post(
        _post(deadline=None), today=date(2026, 10, 31)
    ) is None


def test_expired_employer_advert_cannot_reenter_history_as_new_vacancy():
    assert life_sciences.classify_post(
        _post(deadline=date(2026, 10, 30)), today=date(2026, 10, 31)
    ) is None


def test_postdoc_only_title_remains_excluded():
    assert life_sciences.classify_post(
        _post(title="Postdoctoral Researcher in CRISPR Screening"),
        today=date(2026, 10, 31),
    ) is None

def test_dual_role_title_is_not_preemptively_deleted_from_historical_export():
    assert not life_sciences.historical_life_title_disqualified(
        "PhD/Postdoc in In Vivo CRISPR Screening"
    )
    assert life_sciences.historical_life_title_disqualified(
        "Postdoctoral Researcher in In Vivo CRISPR Screening"
    )
