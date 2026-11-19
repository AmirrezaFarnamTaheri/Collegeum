"""Prove official-only, bounded multi-page admissions research and provenance."""
from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from tools.update_phd_admissions import (
    extract_official_details,
    investigate_official_pages,
    select_official_links,
)

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
AALTO = "https://www.aalto.fi/en/study-options/doctoral-programme"
BERLIN = "https://berlinschoolofeconomics.de/phd-program/application"


def test_aalto_official_page_keeps_conditional_funding_and_fee_details():
    official = """
    <h1>Aalto Doctoral Programme in Business, Economics and Finance</h1>
    <h2>Application instructions 2027</h2>
    <p>Admission schedule 2027: Application period opens on 8 December 2026
    at 09:00 (UTC+2) and closes on 5 January 2027 at 23:59 (UTC+2).</p>
    <p>Attach electronic application documents before the document deadline
    on 12 January 2027.</p>
    <h3>Language of instruction:</h3><p>English</p>
    <h3>Duration:</h3><p>4 years, full-time</p>
    <h3>Eligibility:</h3><p>Relevant master's degree or corresponding
    degree completed abroad.</p>
    <p>If you are admitted as a full-time doctoral student, you will
    receive funding for the first two years of your studies from the
    School of Business.</p>
    <p>The Doctoral Programme is free of tuition fees.</p>
    """
    fields = extract_official_details(official, evidence_url=AALTO, checked_at=NOW)
    assert fields["application_open_iso"]["value"] == "2026-12-08"
    assert fields["duration"]["value"] == "4 years, full-time"
    assert fields["language"]["value"] == "English"
    assert "master" in fields["entry_requirement"]["value"].lower()
    assert "first two years" in fields["funding_note"]["value"].lower()
    assert fields["tuition"]["value"] == "No tuition fees"
    for field in fields.values():
        assert field["evidence_url"] == AALTO
        assert field["checked_at"] == "2026-11-19T12:00:00Z"
        assert field["evidence_excerpt"]


def test_berlin_official_stipend_does_not_hide_conditions_or_semester_fee():
    html = """
    <h1>Application</h1>
    <p>The application deadline to the Berlin School of Economics PhD
    Program for an intake in October 2027 is January 15, 2027.</p>
    <h2>Requirements</h2>
    <p>Applicants should have a Master's degree in economics or business studies.</p>
    <p>Providing GRE General Test scores is highly recommended but not mandatory.</p>
    <p>Two academic reference letters must be supplied through the portal.</p>
    <h2>Scholarships and fees</h2>
    <p>There are no tuition fees. Berlin School of Economics students
    will receive funding for the expected length of the program.</p>
    <p>For the Qualification Phase, a monthly stipend of 1,650 Euros
    and a family allowance (if applicable) is provided.</p>
    <p>Funding for the Dissertation Phase is conditional on
    having fulfilled the program's performance criteria.</p>
    <p>Member institutions charge a semester fee of approximately
    300-350€ per semester.</p>
    """
    f = extract_official_details(html, evidence_url=BERLIN, checked_at=NOW)
    assert "1,650" in f["stipend"]["value"]
    assert "qualification" in f["stipend"]["value"].lower()
    assert "conditional" in f["funding_note"]["value"].lower()
    assert f["tuition"]["value"] == "No tuition fees"
    assert "300" in f["semester_fee"]["value"]
    assert "not mandatory" in f["tests"]["value"].lower()
    assert "two" in f["references"]["value"].lower()


def test_irrelevant_dates_and_unqualified_promises_are_not_details():
    html = """
    <h1>Doctoral programme in economics</h1>
    <p>Our research symposium starts on 8 December 2026.</p>
    <p>Scholarships may be available, contact the faculty.</p>
    <p>A fee waiver is offered only to visiting faculty.</p>
    <p>IELTS scores are required for admission for selected routes.</p>
    """
    f = extract_official_details(html, evidence_url=AALTO, checked_at=NOW)
    assert "application_open_iso" not in f
    assert "stipend" not in f
    assert "tuition" not in f
    assert "funding_note" not in f
    assert "tests" not in f


def test_follow_only_bounded_relevant_same_host_https_html_links():
    html = """
    <h1>Economics PhD</h1>
    <a href="/phd/apply">How to apply for PhD</a>
    <a href="/phd/admissions/deadlines">Admission deadlines</a>
    <a href="https://collector.example.org/phd/deadlines">Admissions list</a>
    <a href="https://www.aalto.fi/phd/fees">Fees and funding</a>
    <a href="/downloads/phd-deadlines.pdf">PDF deadlines</a>
    <a href="/login?redirect=phd">Application portal sign in</a>
    <a href="javascript:alert('x')">Read more</a>
    """
    links = select_official_links(html, AALTO, max_links=2)
    assert len(links) == 2
    assert all(urlparse(url).hostname in {"www.aalto.fi", "aalto.fi"} for url in links)
    assert all(url.startswith("https://") for url in links)
    assert all(not url.endswith(".pdf") for url in links)


def test_deeper_official_admissions_page_can_supply_deadline_with_provenance():
    secondary = "https://www.aalto.fi/phd/admissions"
    docs = {
        AALTO: ("""
            <h1>Doctoral programme in economics</h1>
            <a href="/phd/admissions">PhD application deadlines</a>
            <a href="https://thirdparty.example.edu/phd/deadlines">More dates</a>
            """, AALTO),
        secondary: ("""
            <h1>Economics PhD admission</h1>
            <p>Applications deadline: December 15, 2026.</p>
            <p>The programme is free of tuition fees.</p>
            """, secondary),
    }
    fetched = []

    def fetch(url):
        fetched.append(url)
        return docs[url]

    result = investigate_official_pages(
        AALTO, now=NOW, fetch_html=fetch, robots_allowed=lambda url: True,
        max_pages=3,
    )
    assert result["status"] == "verified"
    assert result["deadline_iso"] == "2026-12-15"
    assert result["evidence_url"] == secondary
    assert result["official_details"]["tuition"]["evidence_url"] == secondary
    assert result["investigated_urls"] == [AALTO, secondary]
    assert len(fetched) == 2


def test_conflicting_same_university_deadlines_fail_closed():
    second = "https://www.aalto.fi/phd/applications"
    docs = {
        AALTO: (
            '<h1>Economics PhD</h1><p>Application deadline: 15 December 2026.</p>'
            '<a href="/phd/applications">PhD application instructions</a>', AALTO
        ),
        second: (
            '<h1>Economics PhD</h1><p>Application deadline: 15 January 2027.</p>',
            second
        ),
    }
    result = investigate_official_pages(
        AALTO, now=NOW, fetch_html=lambda url: docs[url],
        robots_allowed=lambda url: True,
    )
    assert result["status"] == "ambiguous_deadline"
    assert result["deadline_iso"] is None
    assert result["evidence_url"] is None


def test_robots_denial_must_not_be_bypassed_on_linked_page():
    protected = "https://www.aalto.fi/phd/admissions"
    calls = []

    def fetch(url):
        calls.append(url)
        return (
            '<h1>Economics PhD</h1><a href="/phd/admissions">'
            'PhD admissions application deadline</a>', url,
        )

    result = investigate_official_pages(
        AALTO, now=NOW, fetch_html=fetch,
        robots_allowed=lambda url: url != protected,
    )
    assert calls == [AALTO]
    assert result["deadline_iso"] is None
    assert protected not in result["investigated_urls"]


def test_bounded_crawl_never_fetches_more_than_three_pages():
    calls = []

    def fetch(url):
        calls.append(url)
        return (
            '<h1>Economics PhD</h1>' +
            "".join(
                f'<a href="/phd/admissions/{i}">PhD admission deadlines {i}</a>'
                for i in range(20)
            ), url,
        )

    result = investigate_official_pages(
        AALTO, now=NOW, fetch_html=fetch,
        robots_allowed=lambda url: True, max_pages=3,
    )
    assert len(calls) == 3
    assert len(result["investigated_urls"]) == 3


def test_fetch_errors_fail_closed_with_diagnostic_status():
    def fail(_):
        raise TimeoutError("university page did not respond")

    result = investigate_official_pages(
        AALTO, now=NOW, fetch_html=fail,
        robots_allowed=lambda url: True,
    )
    assert result["status"] == "fetch_failed"
    assert result["deadline_iso"] is None
    assert not result["official_details"]


def test_unsupported_pdf_or_external_redirect_cannot_be_verified():
    page = "https://www.aalto.fi/phd/application"
    def redirect(_):
        return (
            "<h1>Economics PhD admissions</h1>"
            "<p>Application deadline: 15 December 2026</p>",
            "https://thirdparty.example.com/phd",
        )
    result = investigate_official_pages(
        page, now=NOW, fetch_html=redirect,
        robots_allowed=lambda url: True,
    )
    assert result["status"] == "unsafe_redirect"
    assert result["deadline_iso"] is None


def test_generic_eligibility_disclaimer_is_not_a_degree_requirement():
    html = """
        <h1>Aalto Doctoral Programme in Business, Economics and Finance</h1>
        <h3>Eligibility:</h3>
        <p>Please note that we cannot confirm the eligibility of an
        individual prospective applicant outside the actual application
        process. Eligibility is assessed based on documents.</p>
    """
    facts = extract_official_details(html, evidence_url=AALTO, checked_at=NOW)
    assert "entry_requirement" not in facts


def test_funding_sentence_retains_conditional_stage_not_promotional_prefix():
    html = """
        <h1>Berlin School of Economics PhD Programme</h1>
        <p>There are no tuition fees. Berlin School of Economics students
        will receive funding for the expected length of the program.
        For the Qualification Phase, a monthly stipend of 1,650 Euros
        is provided. Funding for the Dissertation Phase is conditional on
        having fulfilled the program's performance criteria.</p>
    """
    facts = extract_official_details(html, evidence_url=BERLIN, checked_at=NOW)
    value = facts["funding_note"]["value"].lower()
    assert "funding" in value and "conditional" in value
    assert "dissertation phase" in value
    assert not value.startswith("there are no tuition fees")


def test_link_discovery_prefers_admissions_funding_over_job_market_about_pages():
    page = """
        <h1>Berlin School of Economics PhD application</h1>
        <a href="/job-market/job-market-candidates">PhD job-market candidates</a>
        <a href="/about-us/about-us">About the PhD programme</a>
        <a href="/phd-program/application-schedule">Application deadline</a>
        <a href="/phd-program/funding">Funding and fees</a>
    """
    links = select_official_links(page, BERLIN, max_links=2)
    assert len(links) == 2
    assert any("application" in link for link in links)
    assert any("funding" in link for link in links)
    assert all("job-market" not in link and "about-us" not in link for link in links)


def test_simple_official_label_value_in_div_is_not_lost():
    html = """
        <h1>Aalto Doctoral Programme in Business, Economics and Finance</h1>
        <div>Language of instruction: English</div>
        <div>Duration: 4 years, full-time</div>
    """
    f = extract_official_details(html, evidence_url=AALTO, checked_at=NOW)
    assert f["language"]["value"] == "English"
    assert f["duration"]["value"] == "4 years, full-time"



def test_official_phd_track_is_first_year_of_doctorate_via_masters_stage():
    track_url = "https://bse.eu/masters-degrees/economics-finance/upf-phd-track"
    admission_url = "https://bse.eu/masters-degrees/admissions"
    pages = {
        track_url: (
            "<h1>PhD Track Program</h1>"
            "<p>This program is the first year of the PhD in Economics and "
            "Finance at Universitat Pompeu Fabra (UPF).</p>"
            '<a href="/masters-degrees/admissions">PhD track admissions</a>',
            track_url,
        ),
        admission_url: (
            "<h1>Admission Process for Master’s Degrees</h1>"
            "<p>2027-2028 applications are open! First Round Application "
            "deadline: January 15, 2027.</p>"
            "<p>If you are applying to the PhD Track Program, a GRE score "
            "is required.</p>",
            admission_url,
        ),
    }
    result = investigate_official_pages(
        track_url, now=NOW, fetch_html=lambda url: pages[url],
        robots_allowed=lambda url: True,
    )
    assert result["status"] == "verified"
    assert result["deadline_iso"] == "2027-01-15"
    assert result["evidence_url"] == admission_url
    route = result["official_details"]["admission_route"]
    assert "phd track" in route["value"].lower()
    assert "master" in route["value"].lower()
    assert route["evidence_url"] == track_url


def test_masters_admissions_deadline_does_not_equal_doctoral_admission_without_track():
    programme = "https://bse.eu/programmes/economics-phd"
    admission = "https://bse.eu/masters-degrees/admissions"
    pages = {
        programme: (
            "<h1>Economics PhD prospective students</h1>"
            '<a href="/masters-degrees/admissions">Admissions</a>',
            programme,
        ),
        admission: (
            "<h1>Admission Process for Master’s Degrees</h1>"
            "<p>2027-2028 applications are open. First Round Application "
            "deadline: January 15, 2027.</p>"
            "<p>We provide an Economics PhD track introduction in the FAQ.</p>",
            admission,
        ),
    }
    result = investigate_official_pages(
        programme, now=NOW, fetch_html=lambda url: pages[url],
        robots_allowed=lambda url: True,
    )
    assert result["status"] != "verified"
    assert result["deadline_iso"] is None
    assert "admission_route" not in result["official_details"]


def test_official_admission_route_is_not_derived_from_upstream_hint():
    html = """
        <h1>Economics PhD admission</h1>
        <p>Application deadline: January 15, 2027.</p>
        <p>Master's degree required for entry.</p>
    """
    f = extract_official_details(
        html, evidence_url="https://www.aalto.fi/en/phd", checked_at=NOW,
    )
    assert "admission_route" not in f



def test_phd_track_first_year_fee_and_gre_requirement_are_not_assumed_free():
    page = """
        <h1>PhD Track Program</h1>
        <p>This program is the first year of the PhD in Economics
        and Finance at Universitat Pompeu Fabra (UPF).</p>
        <h2>Tuition Fee</h2><p>Student Fee: €18,500</p>
        <h2>Admissions and Entry Requirements</h2>
        <p>Candidates of the PhD-track program must meet these criteria:
        A GRE score is required to be considered for admission.</p>
        <h2>Tuition Funding and Scholarships</h2>
        <p>Funding opportunities at BSE are awarded on the basis
        of academic excellence.</p>
    """
    official = "https://bse.eu/masters-degrees/economics-finance/upf-phd-track"
    facts = extract_official_details(
        page, evidence_url=official, checked_at=NOW,
    )
    assert "18,500" in facts["tuition"]["value"]
    assert "required" in facts["tests"]["value"].lower()
    assert "merit" in facts["funding_note"]["value"].lower()
    assert "guaranteed" in facts["funding_note"]["value"].lower()
    assert all(item["evidence_url"] == official for item in facts.values())
