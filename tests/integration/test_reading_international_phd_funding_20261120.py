"""Verify a separate university-wide international PhD studentship safely."""
from datetime import UTC, datetime

from predoc_pipeline.publish.official_calls import call_key, eligible_calls
from tools.update_official_calls import extract_call

NOW = datetime(2026, 11, 20, 8, tzinfo=UTC)
READING = (
    "https://www.reading.ac.uk/doctoral-researcher-college/funding/"
    "phd-studentships/international-phd-studentships"
)
SOURCE = {
    "id": "reading-international-studentships", "mode": "detail",
    "institution": "University of Reading", "country_code": "UK",
    "url": READING, "title": "International PhD studentships",
}
HTML = """<html>
<h1>International PhD studentships</h1>
<p>The University is pleased to announce a range of International
PhD studentships available to start in October 2027. We award these to
qualified applicants for research within social sciences and within
the Henley Business School.</p>
<h2>Eligibility</h2>
<p>Applicants must apply for a place on a PhD programme at the University
of Reading by 15th January 2027.</p>
<h2>Deadline</h2>
<p>The deadline for applications is Friday 15th January 2027.</p>
<h2>How to apply</h2>
<p>Complete the International PhD Studentship Competition application form.</p>
</html>"""


def test_official_ordinal_date_and_studentship_deadline_verified():
    call = extract_call(HTML, url=READING, source=SOURCE, now=NOW)
    assert call["status"] == "verified"
    assert call["kind"] == "phd_studentship"
    assert call["intake_year"] == 2027
    assert call["deadline_iso"] == "2027-01-15"
    assert call["deadline_kind"] == "funding"
    assert call["location_evidence"]
    assert eligible_calls({
        "kind": "official_phd_call_observations", "version": 1, "calls": [call],
    }, now=NOW) == [call]


def test_reading_international_scheme_not_same_as_henley_departmental_award():
    call = extract_call(HTML, url=READING, source=SOURCE, now=NOW)
    henley = {
        "official_url": "https://www.henley.ac.uk/study/phds/"
                        "accounting-and-financial-management",
        "intake_year": 2027,
    }
    assert call_key(call) != call_key(henley)


def test_generic_admissions_page_does_not_become_studentship():
    html = HTML.replace(
        "<h1>International PhD studentships</h1>", "<h1>General PhD Admissions</h1>"
    ).replace("International PhD studentships available", "PhD admissions available")
    invalid_source = {**SOURCE, "title": "General PhD Admissions"}
    call = extract_call(html, url=READING, source=invalid_source, now=NOW)
    assert call["status"] != "verified"



def test_navigation_heavy_official_page_uses_content_after_h1_for_subject_scope():
    """Real University of Reading pages include a large menu before the call."""
    navigation = "<nav>" + (
        "<a href='/doctoral-opportunities'>Doctoral opportunities and fees</a>"
        * 35
    ) + "</nav>"
    html = HTML.replace("<h1>", navigation + "<main><h1>").replace(
        "</html>", "</main></html>"
    )
    call = extract_call(html, url=READING, source=SOURCE, now=NOW)
    assert call["status"] == "verified"
    assert call["deadline_iso"] == "2027-01-15"
    assert eligible_calls({
        "kind": "official_phd_call_observations", "version": 1,
        "calls": [call],
    }, now=NOW) == [call]


def test_business_school_navigation_alone_is_not_evidence_of_relevant_funding():
    """Do not claim an unrelated doctoral fund matches Economics by site navigation."""
    navigation = (
        "<nav><a href='/business'>Henley Business School</a>"
        "<a href='/finance'>Finance department</a></nav>"
    )
    unrelated = HTML.replace(
        "qualified applicants for research within social sciences and within\n"
        "the Henley Business School.",
        "applicants exclusively in marine biology and molecular engineering.",
    )
    html = unrelated.replace("<h1>", navigation + "<main><h1>").replace(
        "</html>", "</main></html>"
    )
    call = extract_call(html, url=READING, source=SOURCE, now=NOW)
    assert call["status"] == "unrelated"
    assert eligible_calls({
        "kind": "official_phd_call_observations", "version": 1,
        "calls": [call],
    }, now=NOW) == []
