"""Locale, metadata and role distinctions from the consolidated audit."""

import pytest

from predoc_pipeline.core.textproc import squish
from predoc_pipeline.core.urls import content_hash
from predoc_pipeline.models import parse_salary, sanitize_summary
from predoc_pipeline.routing import Router


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("EUR 3.776,10 per month", (3776.10, 3776.10, "EUR", "month")),
        ("CAD $60,000/year", (60000, 60000, "CAD", "year")),
        ("A$60,000/year", (60000, 60000, "AUD", "year")),
        ("CHF 60'000 per year", (60000, 60000, "CHF", "year")),
        ("EUR 3 776,10 per month", (3776.10, 3776.10, "EUR", "month")),
        ("£22.50 per hour", (22.50, 22.50, "GBP", "hour")),
        ("$55k - 65k / yr", (55000, 65000, "USD", "year")),
        ("EUR 3.776,10–4.200,50 monthly", (3776.10, 4200.50, "EUR", "month")),
        ("USD 60,000/year; 2-year contract starting 2027", (60000, 60000, "USD", "year")),
        ("USD 60,000/year plus USD 5,000 bonus", (60000, 60000, "USD", "year")),
        ("Salary grade 7, EUR 3,200 monthly", (3200, 3200, "EUR", "month")),
        ("EUR 60,000 or USD 65,000 annually", (None, None, None, "year")),
        ("£35–40k per year", (35000, 40000, "GBP", "year")),
        ("EUR 3,200", (3200, 3200, "EUR", None)),
        ("HK$30,000 per month", (30000, 30000, "HKD", "month")),
        ("EUR 3.7.6 per month", (None, None, "EUR", "month")),
    ],
)
def test_salary_locale_and_amount_context(raw, expected):
    assert parse_salary(raw) == expected


@pytest.mark.parametrize("character", ["\u200b", "\ufeff", "\u2060", "\u00ad"])
def test_invisible_artifacts_do_not_change_normalized_identity(character):
    assert squish(f"Research{character} Assistant") == "Research Assistant"
    assert content_hash(f"Research Assistant{character}") == content_hash("Research Assistant")


def test_normalization_preserves_meaningful_joiners():
    assert squish("👩\u200d🔬") == "👩\u200d🔬"
    assert squish("می\u200cرود") == "می\u200cرود"


@pytest.mark.parametrize("summary", ["", "Ihre Aufgaben: administrative Unterstützung."])
def test_summary_fallback_does_not_invent_duties_or_qualifications(summary):
    text = sanitize_summary(summary, title="Administrative Assistant", institution="Example")
    assert "empirical research" not in text
    assert "academic coursework" not in text
    assert "doctoral studies" not in text
    assert "Full-time" not in text


@pytest.mark.parametrize("summary", [
    "Sponsoring institution: Example University Sponsoring researcher: Ada Lovelace",
    "institution: Example University | pi_name: Ada Lovelace",
])
def test_structured_summary_preserves_explicit_role_category(summary):
    text = sanitize_summary(summary, title="Postdoctoral Fellow")
    assert "Postdoctoral Fellow" in text
    assert "Predoctoral" not in text


@pytest.mark.parametrize(
    "title,summary,kind",
    [
        ("Research Assistant", "The holder will enroll as a doctoral candidate and complete "
         "a PhD dissertation.", "phd"),
        ("University Assistant Predoctoral", "The holder completes a PhD dissertation.", "phd"),
        ("Predoctoral Fellow", "Preparation for applying to PhD programs.", "predoc"),
        ("Research Assistant", "Work with PhD students on economic research.", "predoc"),
        ("Research Assistant", "No doctoral enrollment is required.", "predoc"),
        ("Research Fellow", "A completed PhD is required for this appointment.", "postdoc"),
        ("Research Assistant", "Work with postdoctoral researchers on economics.", "predoc"),
        ("Research Fellow", "This is a postdoctoral appointment in economics.", "postdoc"),
        ("Research Assistant", "The holder may pursue a PhD degree later.", "predoc"),
    ],
)
def test_role_type_uses_explicit_holder_requirements(title, summary, kind):
    assert Router.position_kind(title, summary) == kind


@pytest.mark.parametrize(
    "raw,country,expected",
    [
        ("Vergütungsgruppe TV-L E 13", "Germany", (None, None, None, None)),
        ("salary scale 13 TV-L, 100%", "Germany", (None, None, None, None)),
        ("2026 rates, uplifted from April 2027", "United Kingdom",
         (None, None, None, None)),
        ("Grade 6 - £31,236 - £36,636 / Grade 7, £37,694 - £43,482 per annum",
         "United Kingdom", (None, None, "GBP", "year")),
        ("$91,546 - $141,317 per annum plus 17 % superannuation",
         "Australia", (91546, 141317, "AUD", "year")),
        ("3400€ brut/mois", "France", (3400, 3400, "EUR", "month")),
    ],
)
def test_real_publication_salary_regressions(raw, country, expected):
    assert parse_salary(raw, country=country) == expected


def test_bank_of_canada_verified_salary_range_remains_parseable():
    amount = (
        "Starting annual base salary CAD $114,952.50–$156,778.00 "
        "per year (2026 scales)"
    )
    assert parse_salary(amount, country="Canada") == (
        114952.5, 156778.0, "CAD", "year"
    )
