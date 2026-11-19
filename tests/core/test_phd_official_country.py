"""Country of an official non-US PhD programme must be corroborated by the university."""
from __future__ import annotations

from datetime import UTC, datetime

from tools.update_phd_admissions import (
    extract_official_country,
    investigate_official_pages,
)

NOW = datetime(2026, 11, 19, 14, 0, tzinfo=UTC)
BSE = "https://bse.eu/masters-degrees/economics-finance/upf-phd-track"
CONTACT = "https://bse.eu/contact"
ADMISSIONS = "https://bse.eu/masters-degrees/admissions"


def test_official_contact_address_proves_non_us_country_on_eu_domain():
    docs = {
        BSE: (
            "<h1>PhD Track Program</h1>"
            "<p>This program is the first year of the PhD in Economics "
            "and Finance at Universitat Pompeu Fabra.</p>"
            '<a href="/masters-degrees/admissions">PhD Track admissions</a>'
            '<a href="/contact">Contact us</a>',
            BSE,
        ),
        ADMISSIONS: (
            "<h1>Admission Process for Master’s Degrees</h1>"
            "<p>2027-28 applications are open. First Round Application "
            "deadline: January 15, 2027.</p>"
            "<p>GRE is required for the PhD Track Program.</p>",
            ADMISSIONS,
        ),
        CONTACT: (
            "<h1>Contact us</h1><h2>Mailing Address</h2>"
            "<p>Barcelona School of Economics, Ramon Trias Fargas 25-27, "
            "08005 Barcelona, Catalonia, Spain</p>",
            CONTACT,
        ),
    }
    requested = []

    def fetch(url: str) -> tuple[str, str]:
        requested.append(url)
        return docs[url]

    result = investigate_official_pages(
        BSE, now=NOW, fetch_html=fetch,
        robots_allowed=lambda url: True, max_pages=4,
    )
    assert result["status"] == "verified"
    assert result["deadline_iso"] == "2027-01-15"
    assert result["official_details"]["admission_route"]["value"].startswith("PhD track")
    country = result["official_details"]["institution_country"]
    assert country["value"] == "Spain"
    assert country["evidence_url"] == CONTACT
    assert "Barcelona" in country["evidence_excerpt"]
    assert country["checked_at"] == "2026-11-19T14:00:00Z"
    assert CONTACT in result["investigated_urls"]
    assert len(requested) <= 4
    assert all(url.startswith("https://bse.eu/") for url in requested)


def test_country_from_unrelated_study_abroad_or_time_zone_must_not_be_used():
    misleading = """
        <h1>Economics PhD admissions</h1>
        <p>Our students have visited Spain, France and the United States.</p>
        <p>Application deadline: 15 January 2027 at 14:00 CET (time in Italy).</p>
    """
    assert extract_official_country(
        misleading, evidence_url=BSE, checked_at=NOW
    ) is None


def test_official_address_in_footer_can_corrobate_italian_institution():
    html = """
        <h1>Doctoral Programme in Economics</h1>
        <p>The deadline to apply is 15 January 2027 (time in Italy).</p>
        <footer><address>European University Institute, Via dei Roccettini 9,
        I-50014 San Domenico di Fiesole (FI), Italy</address></footer>
    """
    fact = extract_official_country(
        html, evidence_url="https://www.eui.eu/apply?id=doctoral-programme-in-economics",
        checked_at=NOW,
    )
    assert fact is not None
    assert fact["value"] == "Italy"
    assert fact["evidence_url"].startswith("https://www.eui.eu/")
    assert "Fiesole" in fact["evidence_excerpt"]


def test_copyright_footer_with_full_postal_address_is_proof():
    html = """
        <h1>Doctoral Programme in Economics</h1>
        <p>Deadline 15 January 2027 at 14:00 CET (Time in Italy).</p>
        <footer>© European University Institute 2026, Badia Fiesolana -
        Via dei Roccettini 9, I-50014 San Domenico di Fiesole (FI) - Italy
        </footer>
    """
    fact = extract_official_country(
        html, evidence_url="https://www.eui.eu/apply?id=doctoral-programme-in-economics",
        checked_at=NOW,
    )
    assert fact is not None
    assert fact["value"] == "Italy"
    assert "I-50014" in fact["evidence_excerpt"]


def test_copyright_mention_without_postal_address_is_not_location_proof():
    html = """
        <h1>Economics PhD</h1>
        <p>Current application deadlines are displayed in Italy time.</p>
        <footer>© Example 2026. Applicants from Spain welcome.</footer>
    """
    assert extract_official_country(html, evidence_url=BSE, checked_at=NOW) is None


def test_robots_disallowed_contact_page_is_never_read():
    def page(url: str) -> tuple[str, str]:
        assert url == BSE
        return (
            "<h1>PhD Track Program</h1>"
            '<a href="/contact">Contact us</a>',
            url,
        )

    result = investigate_official_pages(
        BSE, now=NOW, fetch_html=page,
        robots_allowed=lambda url: url != CONTACT, max_pages=4,
    )
    assert "institution_country" not in result["official_details"]
    assert CONTACT not in result["investigated_urls"]


def test_conflicting_official_contact_countries_fail_closed():
    html = """
        <h1>Contact</h1><h2>Mailing Address</h2>
        <p>Campus 1, 08005 Barcelona, Spain</p>
        <p>Campus 2, 75001 Paris, France</p>
    """
    assert extract_official_country(html, evidence_url=CONTACT, checked_at=NOW) is None
