"""Official funding calls must be discoverable on Pages, not only Telegram."""
from pathlib import Path


def test_pages_exports_independent_public_call_catalogue():
    workflow = Path(".github/workflows/pages.yml").read_text(encoding="utf-8")
    stage = workflow.split("- name: Stage public dashboard assets", 1)[1].split(
        "- name: Stage upstream MIT attribution", 1
    )[0]
    assert "official_phd_calls.json" in stage
    assert "build/pages/data" in stage


def test_dashboard_has_distinct_funding_calls_section_and_loading_error():
    html = Path("docs/index.html").read_text(encoding="utf-8")
    assert 'id="official-calls-heading"' in html
    assert 'id="official-calls-summary"' in html
    assert 'id="official-calls-results"' in html
    assert "fetch('data/official_phd_calls.json'" in html
    assert "official_phd_call_observations" in html
    assert "Official funding-call catalogue unavailable" in html
    assert "Independent PhD funding calls" in html


def test_calls_do_not_become_vacancy_entries_or_unverified_deadline_claims():
    html = Path("docs/index.html").read_text(encoding="utf-8")
    assert "row.status === 'verified'" in html
    assert "row.evidence_url === row.official_url" in html
    assert "row.location_evidence_url === row.official_url" in html
    assert "Date.parse(row.checked_at)" in html
    assert "row.deadline_kind === 'funding'" in html
    assert "No employment vacancy is implied" in html
    assert "official-calls-results" not in html.split(
        '<!-- Admissions research:', 1
    )[0]
