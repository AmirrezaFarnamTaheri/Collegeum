import json
from datetime import date

from predoc_pipeline.boards.config import SourceConfig
from predoc_pipeline.boards.http import HttpClient
from predoc_pipeline.boards.scrapers.link_scan import LinkScanScraper
from predoc_pipeline.boards.scrapers.linkedin_scraper import LinkedInScraper, parse_cards
from predoc_pipeline.boards.scrapers.predoc_org import PredocOrgScraper
from predoc_pipeline.boards.scrapers.rss import RSSScraper
from predoc_pipeline.boards.scrapers.university_ats import (
    VarbiScraper,
    WorkdayScraper,
    parse_workday_url,
)
from tests.boards.conftest import fixture_text


def make(cls, **cfg):
    cfg.setdefault("name", "t")
    cfg.setdefault("type", cls.type_name)
    return cls(SourceConfig(**cfg), HttpClient())


def test_predoc_org():
    s = make(PredocOrgScraper, url="https://predoc.org/opportunities", field_implied=True)
    posts = s.parse_postings([("https://predoc.org/opportunities", fixture_text("predoc_org.html"))])
    assert [p.title for p in posts] == ["Predoctoral Staff Associate",
                                        "Research Assistant, Finance, Accounting & Economics",
                                        "Pre-Doctoral Research Assistant", "Research Assistant (Pre-Doc Intern)",
                                        "Pre-Doctoral Research Associate", "Predoctoral Research Fellow"]
    nd = posts[4]
    # "Deadline/First Review Date" and "Start Date" are separate labels, not part of the fields text
    assert nd.fields_of_research == "Developmental psychology, clinical psychology"
    assert nd.deadline == date(2027, 5, 24)
    upf = posts[2]
    assert upf.institution == "Universitat Pompeu Fabra, Barcelona, Spain"
    assert upf.pi_name == "Jan Eeckhout"
    assert upf.deadline == date(2026, 12, 20)
    assert upf.visa_note.startswith("Visas for international candidates")
    assert posts[0].deadline == date(2026, 10, 7)
    assert posts[3].deadline is None and posts[3].deadline_text == "Rolling"
    assert all(p.field_implied for p in posts)


def test_linkedin_cards():
    cards = parse_cards(fixture_text("linkedin_search.html"))
    assert [c["id"] for c in cards] == ["4012345678", "4099999999"]
    posts = make(LinkedInScraper).parse_postings(cards)
    assert posts[0].url == "https://www.linkedin.com/jobs/view/4012345678"
    assert posts[0].institution == "University of Oxford"
    assert posts[0].date_posted == date(2026, 9, 20)


def test_workday():
    assert parse_workday_url("https://ubc.wd10.myworkdayjobs.com/en-US/ubcstaffjobs") == \
        ("ubc.wd10.myworkdayjobs.com", "ubc", "ubcstaffjobs", "en-US")
    s = make(WorkdayScraper, url="https://ubc.wd10.myworkdayjobs.com/ubcstaffjobs", institution="UBC", country="Canada")
    posts = s.parse_postings(json.loads(fixture_text("workday_jobs.json"))["jobPostings"])
    assert posts[0].url.startswith("https://ubc.wd10.myworkdayjobs.com/ubcstaffjobs/job/UBC-Vancouver-Campus/")
    assert posts[0].date_posted == date(2026, 9, 21)
    assert posts[0].institution == "UBC" and posts[0].country == "Canada"


def test_varbi():
    s = make(VarbiScraper, url="https://su.varbi.com/en/", institution="Stockholm University")
    posts = s.parse_postings([("https://su.varbi.com/en/", fixture_text("varbi.html"))])
    assert len(posts) == 3  # job-alert link is not a job
    econ = posts[0]
    assert econ.url == "https://su.varbi.com/en/what:job/jobID:971001"
    assert econ.department == "Department of Economics"
    assert econ.deadline == date(2026, 10, 15)


def test_ku_table_bare_deadline():
    s = make(LinkScanScraper, url="https://employment.ku.dk/all-vacancies/",
             link_pattern=r"all-vacancies/?\?show=\d+", bare_date_is_deadline=True)
    posts = s.parse_postings([("https://employment.ku.dk/all-vacancies/", fixture_text("ku.html"))])
    assert posts[1].title == "Research Assistant in Economics"
    assert posts[1].deadline == date(2026, 10, 12)
    assert "Department of Economics" in posts[1].department


def test_jobs_ac_uk_context():
    s = make(LinkScanScraper, url="https://www.jobs.ac.uk/search/", link_pattern=r"jobs\.ac\.uk/job/[A-Z0-9]+/",
             institution_from_context=True)
    posts = s.parse_postings([("https://www.jobs.ac.uk/search/", fixture_text("jobs_ac_uk.html"))])
    ra = posts[0]
    assert ra.institution == "London School of Economics and Political Science"
    assert ra.deadline == date(2026, 11, 28)
    assert ra.url == "https://www.jobs.ac.uk/job/DSY041/research-assistant"


def test_rss_substack_role_at_institution():
    s = make(RSSScraper, url="x", title_format="role_at_institution", field_implied=True)
    posts = s.parse_postings([fixture_text("substack.xml")])
    assert posts[0].title == "Predoctoral Research Assistant in Development Economics"
    assert posts[0].institution == "London School of Economics"
    assert posts[0].location == "UK"
    assert posts[0].deadline == date(2026, 11, 30)


def test_rss_inomics_filters_non_jobs_and_odd_dates():
    s = make(RSSScraper, url="x", include_url_contains=["/job/"])
    posts = s.parse_postings([fixture_text("inomics.xml")])
    assert len(posts) == 2
    assert posts[1].deadline == date(2026, 10, 31)
    assert posts[1].date_posted == date(2026, 9, 24)


def test_link_scan_pagination_url_formatting():
    s = make(LinkScanScraper, url="https://example.com/jobs", pagination_param="page", max_pages=3)
    assert s._format_page_url("https://example.com/jobs", "page", 1) == "https://example.com/jobs"
    assert s._format_page_url("https://example.com/jobs", "page", 2) == "https://example.com/jobs?page=2"
    assert s._format_page_url("https://example.com/jobs?cat=econ", "page", 3) == "https://example.com/jobs?cat=econ&page=3"
    assert s._format_page_url("https://example.com/jobs/p/{page}/", "page", 2) == "https://example.com/jobs/p/2/"

