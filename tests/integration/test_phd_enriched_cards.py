"""Telegram programme cards share the existing vacancy-card layout and provenance."""
from __future__ import annotations

from predoc_pipeline.publish.admissions import _message

NOW = "2026-11-19T12:00:00Z"
AALTO = "https://www.aalto.fi/en/study-options/economics-phd"


def _row() -> dict:
    return {
        "institution": "Aalto University",
        "country_code": "FI",
        "official_programme_url": AALTO,
        "status": "verified",
        "deadline_iso": "2027-01-05",
        "checked_at": NOW,
        "evidence_url": AALTO,
        "evidence_excerpt": "Economics PhD deadline closes 5 January 2027",
        "official_details": {},
    }


def _fact(value: str, url: str = AALTO, checked: str = NOW) -> dict:
    return {
        "value": value, "evidence_url": url,
        "evidence_excerpt": "University explicitly states: " + value,
        "checked_at": checked,
    }


def test_matches_legacy_collegeum_cards_and_shows_only_official_facts():
    row = _row()
    row["official_details"] = {
        "duration": _fact("4 years, full-time"),
        "language": _fact("English"),
        "tuition": _fact("No tuition fees"),
        "application_open_iso": _fact("2026-12-08"),
        "funding_note": _fact(
            "If admitted full-time, the first two years are funded "
            "by the School of Business."
        ),
        "entry_requirement": _fact("Relevant master's degree"),
    }
    body, keyboard = _message(row)
    assert body.startswith("🎓 <b>")
    assert "<i>Aalto University</i>" in body
    assert "📍 Finland" in body
    assert "🔬 Economics" in body
    assert "⏳ 4 years, full-time" in body
    assert "📅 <b>05 Jan 2027</b>" in body
    assert "English" in body
    assert "08 Dec 2026" in body
    assert "first two years" in body
    assert "No tuition fees" in body
    assert "not an employment vacancy" in body
    assert "#Economics" in body and "#PhD" in body
    assert len(body) < 4096
    assert keyboard["inline_keyboard"][0][0]["url"].startswith("https://")
    assert not any(
        b["text"].lower().find("save") != -1
        for row_buttons in keyboard["inline_keyboard"] for b in row_buttons
    )


def test_metadata_from_nonofficial_or_stale_page_must_never_be_rendered():
    row = _row()
    row["official_details"] = {
        "funding_note": _fact(
            "Guaranteed €99,999 annual stipend", "https://thirdparty.example.com/phd"
        ),
        "tuition": _fact("No tuition fees", checked="2025-09-01T00:00:00Z"),
    }
    body, _ = _message(row)
    assert "99,999" not in body
    assert "No tuition fees" not in body
    assert "Funding: not verified" in body


def test_malicious_university_markup_is_escaped():
    row = _row()
    row["institution"] = "<a href='https://attacker.test'>Aalto</a>"
    row["official_details"] = {
        "entry_requirement": _fact("<script>alert('test')</script>")
    }
    html, _ = _message(row)
    assert "<script>" not in html
    assert "href='https://attacker.test'" not in html
    assert "&lt;script&gt;" in html



def test_verified_phd_track_masters_route_is_labelled_not_misrepresented():
    row = _row()
    official = "https://bse.eu/masters-degrees/economics-finance/upf-phd-track"
    row.update(
        institution="Barcelona School of Economics", country_code="ES",
        official_programme_url=official,
        evidence_url="https://bse.eu/masters-degrees/admissions",
        deadline_iso="2027-01-15",
    )
    row["official_details"] = {
        "admission_route": {
            "value": "PhD track — first-year Master's-stage entry",
            "evidence_url": official,
            "evidence_excerpt": (
                "This program is the first year of the PhD in Economics and "
                "Finance at Universitat Pompeu Fabra (UPF)."
            ),
            "checked_at": NOW,
        },
    }
    body, _ = _message(row)
    assert "PhD track" in body
    assert "Master" in body
    assert "🎓 Entry route:" in body
    assert "not an employment vacancy" in body
