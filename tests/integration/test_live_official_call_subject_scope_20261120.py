"""Live university navigation must not hide or fake subject eligibility."""
from datetime import UTC, datetime

from predoc_pipeline.publish.official_calls import _message
from tools.update_official_calls import extract_call

NOW = datetime(2026, 11, 20, 8, tzinfo=UTC)
URL = (
    "https://www.reading.ac.uk/doctoral-researcher-college/funding/"
    "phd-studentships/international-phd-studentships"
)
SOURCE = {
    "id": "reading-international-studentships", "mode": "detail",
    "institution": "University of Reading", "country_code": "UK",
    "url": URL, "title": "International PhD studentships",
}
# Live Reading pages carry large site navigation before the actual funding call.
NAV = "<nav>" + "<a>University Home | Research | Doctoral College | News</a>" * 30 + "</nav>"
CALL_BODY = """
<h1>International PhD studentships</h1>
<p>The University offers International PhD studentships commencing October 2027
for applicants undertaking social sciences research or within Henley Business School.</p>
<h2>Deadline</h2>
<p>The deadline for applications is Friday 15th January 2027.</p>
"""


def test_long_unrelated_navigation_does_not_hide_subject_relevance():
    call = extract_call(NAV + CALL_BODY, url=URL, source=SOURCE, now=NOW)
    assert call["status"] == "verified"
    assert call["deadline_iso"] == "2027-01-15"


def test_business_word_in_navigation_does_not_make_medical_call_economics_relevant():
    medical = """
<h1>International PhD studentships</h1>
<p>This competition is restricted to clinical medicine and veterinary science
PhD applicants starting October 2027.</p>
<h2>Deadline</h2>
<p>The deadline for applications is Friday 15th January 2027.</p>
"""
    misleading_nav = "<nav><a>Business news</a></nav>" + NAV
    row = extract_call(misleading_nav + medical, url=URL, source=SOURCE, now=NOW)
    assert row["status"] == "unrelated"


def test_broad_international_award_is_not_labeled_economics_only():
    call = extract_call(NAV + CALL_BODY, url=URL, source=SOURCE, now=NOW)
    html, _ = _message(call)
    assert "#PhD #Scholarships" in html
    assert "#Economics" not in html


def test_economics_specific_call_retains_economics_tag():
    economics = {
        **SOURCE, "id": "ieb-economics", "institution": "IEB",
        "country_code": "ES", "url": "https://ieb.ub.edu/en/phd-scholarship-in-economics-2027/",
    }
    html = """
<h1>PhD Scholarship in Economics 2027</h1>
<p>Interested candidates must complete both application steps by 11 December 2026.
08034 Barcelona, C/ John M. Keynes; Tel. +34 93 403 46 46.</p>
"""
    call = extract_call(html, url=economics["url"], source=economics, now=NOW)
    assert call["status"] == "verified"
    text, _ = _message(call)
    assert "#Economics" in text
