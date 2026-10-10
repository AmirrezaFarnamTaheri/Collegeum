import pytest

from predoc_pipeline.boards.heuristics import PHD_REQUIRED, apply_heuristics, detect_visa
from predoc_pipeline.boards.models import JobPostSchema


@pytest.mark.parametrize("text,prefix", [
    ("Unfortunately we are unable to sponsor visas for this role.", "No sponsorship"),
    ("Applicants must be U.S. citizens or permanent residents.", "No sponsorship"),
    ("This position is open only to EU citizens.", "No sponsorship"),
    ("Visa sponsorship is available for the successful candidate.", "Visa support"),
    ("Visas for international candidates outside of the EU will be supported.", "Visa support"),
    ("You must have the right to work in the UK.", "Existing work authorisation"),
])
def test_visa(text, prefix):
    assert detect_visa(text).startswith(prefix)


def test_visa_none():
    assert detect_visa("We offer a competitive salary and a friendly team.") is None


@pytest.mark.parametrize("text,required", [
    ("Candidates must hold a PhD in economics.", True),
    ("PhD required.", True),
    ("Applicants should have a PhD (or be close to completion).", True),
    ("Ideal for students planning to apply to PhD programs.", False),
    ("A bachelor's or master's degree in economics.", False),
])
def test_phd_required(text, required):
    assert bool(PHD_REQUIRED.search(text)) is required


def test_apply_heuristics_fills_gaps_only():
    p = JobPostSchema(title="Predoc RA", url="https://x.org/1", source="t", pi_name="Given Name")
    apply_heuristics(p, "You will work with Professor Ana Lopez. Deadline: 1 December 2026. Based in Madrid, Spain.")
    assert p.pi_name == "Given Name"
    assert p.deadline.isoformat() == "2026-12-01"
    assert p.region == "Europe" and p.country == "Spain"


from predoc_pipeline.boards.heuristics import detect_closed  # noqa: E402
from predoc_pipeline.boards.utils.geo import (  # noqa: E402
    location_from_labels,
    region_from_url,
    us_signal_count,
)


@pytest.mark.parametrize("text,closed", [
    ("Applications will be reviewed until the position is filled.", False),
    ("Once the position is filled we will notify all applicants.", False),
    ("Applications close on 1 December 2026.", False),
    ("This position has been filled. Thank you for your interest.", True),
    ("Predoc 2026 application. This form is no longer accepting responses.", True),
    ("No longer accepting applications", True),
    ("Applications are now closed.", True),
    ("This job posting has expired.", True),
])
def test_detect_closed(text, closed):
    assert bool(detect_closed(text)) is closed


@pytest.mark.parametrize("url,region", [
    ("https://populationanalytics.nd.edu/careers", "US"),
    ("https://www.econ.uzh.ch/en/jobs.html", "Europe"),
    ("https://www.upf.edu/web/econ", "Europe"),          # European school on .edu
    ("https://www.insead.edu/jobs/x-1", "Europe"),
    ("https://www.ox.ac.uk/jobs", "UK"),
    ("https://www.ubc.ca/jobs", "Canada"),
    ("https://unimelb.edu.au/jobs", "Other"),
    ("https://bit.ly/abc", None),                        # shortener says nothing
    ("https://apply.interfolio.com/12345", None),
])
def test_region_from_url(url, region):
    assert region_from_url(url)[1] == region


def test_location_label_and_us_signals():
    assert location_from_labels("Start: Sept. Location: Zurich, Switzerland. Salary: CHF")[1] == "Europe"
    assert us_signal_count("Notre Dame, IN 46556. We use E-Verify. Salary $52,000.") >= 2
    assert us_signal_count("Salary: £38,000, London") == 0


def test_dead_or_redirected_detail_sets_region_and_closed():
    p = JobPostSchema(title="Predoc", url="https://bit.ly/x", source="t")
    p.extra["final_url"] = "https://econ.example.edu/predoc"
    apply_heuristics(p, "Predoctoral fellow in labor economics. This position has been filled.")
    assert p.region == "US" and p.extra["closed"]


def test_euraxess_status_expired_anywhere_on_page():
    page = "third-party-funded academic staff member (pre doc). " + ("Lorem ipsum dolor sit amet. " * 400) + \
           "Deadline 14 Oct 2026. STATUS: EXPIRED"
    assert detect_closed(page) == "STATUS: EXPIRED"


def test_citizen_priority_is_a_visa_note():
    note = detect_visa("All qualified candidates are encouraged to apply; however Canadians and permanent "
                       "residents will be given priority.")
    assert note.startswith("Priority to citizens/residents")


def test_start_date_passed():
    from predoc_pipeline.boards.heuristics import start_date_passed
    assert start_date_passed("Start date negotiable: from July to September 2025.")      # a year ago
    assert start_date_passed("Start date: 1 September 2026") is None                     # within grace
    assert start_date_passed("Start date: September 2027") is None


def _wd_transport(api_json=None, status=200):
    import httpx
    def handler(request):
        url = str(request.url)
        if url.startswith("https://bit.ly/"):
            return httpx.Response(302, headers={"Location": "https://ubc.wd10.myworkdayjobs.com/ubcstaffjobs/job/"
                                                             "UBC-Vancouver-Campus/Research-Assistant--Pre-Doc-Intern-_JR26112"})
        if "/wday/cxs/ubc/ubcstaffjobs/job/" in url:
            return httpx.Response(status, json=api_json or {})
        return httpx.Response(200, text="<html><body><div id='root'></div></body></html>")  # empty JS shell
    return httpx.MockTransport(handler)


@pytest.mark.parametrize("api,status,closed", [
    ({"jobPostingInfo": {"title": "RA", "canApply": True, "endDate": "2026-10-05",
                         "jobDescription": "<p>Vancouver School of Economics. Canadians and permanent residents "
                                           "will be given priority.</p>"}}, 200, None),
    ({"jobPostingInfo": {"title": "RA", "canApply": False}}, 200, "applications closed"),
    ({"jobPostingInfo": {"title": "RA", "canApply": True, "endDate": "2026-09-01"}}, 200, "posting ended"),
    ({}, 404, "HTTP 404"),
])
def test_workday_links_are_checked_through_the_api(api, status, closed, monkeypatch):
    import asyncio
    from datetime import date

    from predoc_pipeline.boards.heuristics import _GenericOpenerForTests, check_still_open
    from predoc_pipeline.boards.http import HttpClient
    monkeypatch.setattr("predoc_pipeline.boards.scrapers.university_ats.today", lambda: date(2026, 10, 5))
    monkeypatch.setattr("predoc_pipeline.boards.utils.dates.today", lambda: date(2026, 10, 5))
    http = HttpClient(transport=_wd_transport(api, status), default_min_interval=0, max_retries=0)
    p = JobPostSchema(title="Research Assistant (Pre-Doc Intern)", url="https://bit.ly/3VuuwHD", source="predoc_org")
    reason = asyncio.run(check_still_open(_GenericOpenerForTests(http), p))
    if closed is None:
        assert reason is None and p.deadline.isoformat() == "2026-10-05"
    else:
        assert closed in reason


@pytest.mark.parametrize("text,required", [
    ("Applicants must hold a PhD in economics.", True),
    ("A completed PhD is required.", True),
    ("Candidates holding a PhD are not eligible for this pre-doctoral position.", False),
    ("You must not hold a PhD.", False),
    ("Applicants should not have completed a PhD.", False),
    ("Ideal for those who plan to apply to PhD programmes.", False),
])
def test_phd_required_ignores_negations(text, required):
    from predoc_pipeline.boards.heuristics import phd_required
    assert phd_required(text) is required
