"""Regression coverage for live Wharton/Penn Workday pages and safe URL parsing.

The collection logs contain wd1.myworkdaysite.com/recruiting/upenn/... URLs;
these are JavaScript job shells, not trustworthy detail text.
"""

import asyncio


PENN = (
    "https://wd1.myworkdaysite.com/en-US/recruiting/upenn/Wharton/job/"
    "Dinan-Hall---4th-Floor/Pre-Doctoral-Research-Specialist--Real-Estate-Center-_JR00124462"
)
EXPECTED_PATH = (
    "/job/Dinan-Hall---4th-Floor/"
    "Pre-Doctoral-Research-Specialist--Real-Estate-Center-_JR00124462"
)


def test_myworkdaysite_recruiting_job_url_resolves_to_correct_cxs_tenant():
    from predoc_pipeline.boards.scrapers.university_ats import workday_parts_from_url

    assert workday_parts_from_url(PENN) == (
        "wd1.myworkdaysite.com", "upenn", "Wharton", EXPECTED_PATH
    )
    assert workday_parts_from_url(
        "https://wd1.myworkdaysite.com/recruiting/upenn/careers-at-penn/"
        "job/Pre-Doctoral-Research-Specialist_JR00127654"
    ) == (
        "wd1.myworkdaysite.com", "upenn", "careers-at-penn",
        "/job/Pre-Doctoral-Research-Specialist_JR00127654",
    )


def test_workday_detail_reader_uses_job_api_not_javascript_shell():
    from predoc_pipeline.boards.models import JobPostSchema
    from predoc_pipeline.boards.scrapers.base import generic_fetch_detail

    class FakeHTTP:
        def __init__(self):
            self.requests = []

        async def get_json(self, url, **kwargs):
            self.requests.append((url, kwargs))
            return {"jobPostingInfo": {
                "title": "Pre-Doctoral Research Specialist",
                "jobDescription": "<p>Economic research with R and Stata.</p>",
                "location": "Philadelphia",
                "canApply": True,
            }}

        async def request(self, *_args, **_kwargs):
            raise AssertionError("Must not interpret Workday HTML JS shell as vacancy text")

    http = FakeHTTP()
    post = JobPostSchema(title="Pre-Doctoral Research Specialist", url=PENN, source="test")
    result = asyncio.run(generic_fetch_detail(http, post))
    assert "Economic research with R and Stata" in result
    assert http.requests == [(
        "https://wd1.myworkdaysite.com/wday/cxs/upenn/Wharton" + EXPECTED_PATH,
        {"headers": {"Accept": "application/json"}},
    )]
    assert post.extra["final_url"] == PENN


def test_only_exact_workday_hosts_and_well_formed_paths_are_accepted():
    from predoc_pipeline.boards.scrapers.university_ats import workday_parts_from_url

    assert workday_parts_from_url(
        "https://ubc.wd10.myworkdayjobs.com/en-US/ubcstaffjobs/job/UBC/RA_JR26112"
    ) == (
        "ubc.wd10.myworkdayjobs.com", "ubc", "ubcstaffjobs",
        "/job/UBC/RA_JR26112",
    )
    bad = [
        "https://ubc.wd10.myworkdayjobs.com.evil.invalid/ubcstaffjobs/job/RA",
        "https://wd1.myworkdaysite.com.evil.invalid/recruiting/upenn/Wharton/job/RA",
        "https://wd1.myworkdaysite.com/recruiting/upenn/job/RA",
        "https://wd1.myworkdaysite.com/recruiting/upenn/Wharton/jobs",
        "https://attacker@wd1.myworkdaysite.com/recruiting/upenn/Wharton/job/RA",
        "http://wd1.myworkdaysite.com/recruiting/upenn/Wharton/job/RA",
        "https://example.invalid/redirect?next=https://wd1.myworkdaysite.com/job/RA",
    ]
    assert all(workday_parts_from_url(url) is None for url in bad)
