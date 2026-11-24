"""Official university contracts: current captures and fail-closed boundaries."""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup

from predoc_pipeline.boards.collector import _collect
from predoc_pipeline.boards.config import load_board_sources, load_preferences
from predoc_pipeline.boards.http import FetchError
from predoc_pipeline.boards.scrapers.official_university import (
    OfficialUniversityScraper,
    _identity,
    _listing_key,
)
from predoc_pipeline.boards.utils.text import canonical_url

FIXTURES = Path("tests/fixtures/boards/official_university_20261124")
NAMES = {
    "vienna": "vienna_university_research",
    "amsterdam": "amsterdam_university_research",
    "maastricht": "maastricht_university_research",
    "utrecht": "utrecht_university_research",
}
DETAILS = {
    "vienna": "https://jobs.univie.ac.at/job/University-assistant-%28predoctoral%29-at-the-Department-of-Political-Science/1455578533/",
    "amsterdam": "https://werkenbij.uva.nl/en/vacancies/postdoctoral-researcher-in-knowledge-security-and-in-a-geopolitical-context-netherlands-15624",
    "maastricht": "https://vacancies.maastrichtuniversity.nl/job/Maastricht-Postdoctoral-Researcher-in-Behavioral-and-Sustainable-Finance/1377839757/",
    "utrecht": "https://www.uu.nl/en/organisation/working-at-utrecht-university/jobs/postdoctoral-researcher-in-transnational-retirement-across-portugal-and-brazil",
}
EXTRA_PAGES = {
    "vienna": {
        "https://jobs.univie.ac.at/go/Postdoc/8879501/": "vienna_postdoc",
        "https://jobs.univie.ac.at/go/Praedoc/8877001/25/?q=&sortColumn=referencedate&sortDirection=desc": "vienna_page2",
    },
    "amsterdam": {
        "https://werkenbij.uva.nl/en/vacancies?o=10": "amsterdam_page2",
        "https://werkenbij.uva.nl/en/vacancies?o=20": "amsterdam_page3",
    },
}


@pytest.fixture(autouse=True)
def fixed_date(monkeypatch):
    monkeypatch.setattr("predoc_pipeline.boards.filter.today", lambda: date(2026, 11, 24))
    monkeypatch.setattr("predoc_pipeline.boards.heuristics._today", lambda: date(2026, 11, 24))


def config(profile):
    return next(s for s in load_board_sources("config/sources.toml") if s.name == NAMES[profile])


def detail(profile):
    return (FIXTURES / f"{profile}_detail.html").read_text()


def pages(profile, *, one=False, target_url=None):
    source = config(profile)
    first = (source.opt("urls") or [source.opt("url")])[0]
    names = {first: f"{profile}_listing", **EXTRA_PAGES.get(profile, {})}
    result = {}
    for url, name in names.items():
        soup = BeautifulSoup((FIXTURES / f"{name}.html").read_text(), "lxml")
        if one:
            # Keep real index structure and nonresearch cards on each page, but
            # leave only the reviewed target eligible for a detail request.
            for card in soup.select("tr.data-row, a.vacancy-item, li.overview-list__item .vacancy"):
                anchor = card.select_one("a.jobTitle-link, h3 a") or card
                href = str(anchor.get("href", ""))
                target = target_url or DETAILS[profile]
                if not target.endswith(href) and canonical_url(href) != canonical_url(target):
                    titles = card.select("a.jobTitle-link, h3 a") or card.select("h3")
                    for title in titles:
                        title.clear()
                        title.append("Administrative coordinator")
        result[canonical_url(url)] = str(soup)
    return result


class PageHttp:
    def __init__(self, listing, body, *, final_url=None, error=None, index_errors=None):
        self.listing, self.body = listing, body
        self.final_url, self.error = final_url, error
        self.index_errors = index_errors or {}
        self.index_requests = []
        self.detail_requests = []

    def set_host_interval(self, url, seconds):
        assert url.startswith("https://") and seconds >= 1.5

    async def get_text(self, url):
        self.index_requests.append(url)
        if canonical_url(url) in self.index_errors:
            raise self.index_errors[canonical_url(url)]
        return self.listing[canonical_url(url)]

    async def request(self, method, url):
        self.detail_requests.append(url)
        if self.error:
            raise self.error
        return httpx.Response(200, text=self.body, request=httpx.Request(method, self.final_url or url))


def collect_one(profile, body=None, *, target_url=None, **kwargs):
    http = PageHttp(pages(profile, one=True, target_url=target_url), detail(profile) if body is None else body, **kwargs)
    prefs = load_preferences("config/preferences.toml")
    run = asyncio.run(_collect([config(profile)], prefs, lambda _: False, http))
    return run, http


@pytest.mark.parametrize(("profile", "count", "requests"), [
    ("vienna", 28, 3), ("amsterdam", 18, 3), ("maastricht", 9, 1), ("utrecht", 5, 1),
])
def test_observed_indexes_follow_bounded_pages_and_only_research_roles(profile, count, requests):
    source = config(profile)
    assert source.enabled and not source.field_implied and not source.may_be_empty
    http = PageHttp(pages(profile), "")
    scraper = OfficialUniversityScraper(source, http)
    posts, discovered = asyncio.run(scraper.run())
    assert len(posts) == discovered == count
    assert len(http.index_requests) == requests
    assert len({p.extra["official_requisition_id"] for p in posts}) == count
    assert not scraper.discovery_parse_errors + scraper.discovery_fetch_errors + scraper.discovery_limits
    if profile == "vienna":
        assert all(not p.title.startswith(("Universitäts", "Wiss.")) for p in posts)
        assert all(p.deadline is None for p in posts)  # Datum is the posting date.


@pytest.mark.parametrize(("profile", "deadline", "country"), [
    ("vienna", "2026-11-30", "Austria"),
    ("amsterdam", "2026-11-30", "Netherlands"),
    ("maastricht", "2027-01-10", "Netherlands"),
    ("utrecht", "2027-01-30", "Netherlands"),
])
def test_matching_current_advert_passes_integrated_collection(profile, deadline, country):
    run, http = collect_one(profile)
    assert len(http.detail_requests) == 1
    assert len(run.items) == 1 and run.deferred == 0
    assert run.items[0].hints.get("reject") is None
    assert run.items[0].hints["deadline"] == deadline
    assert run.items[0].hints["country"] == country
    assert run.items[0].hints["country_basis"] == "reviewed_source_profile"


def test_health_economics_uses_actual_duties_despite_broad_medical_faculty_label():
    target = "https://vacancies.maastrichtuniversity.nl/job/Maastricht-Postdoctoraal-onderzoeker-gezondheidseconomie-en-health-technology-assessment/1375965757/"
    body = (FIXTURES / "maastricht_hta_detail.html").read_text()
    run, http = collect_one("maastricht", body, target_url=target)
    assert len(http.detail_requests) == 1
    assert len(run.items) == 1 and not run.items[0].hints.get("reject")
    assert run.items[0].hints["deadline"] == "2026-11-25"
    assert "Medicine" in run.items[0].hints["department"]


@pytest.mark.parametrize("profile", NAMES)
@pytest.mark.parametrize("mutation", ["canonical", "missing_body"])
def test_missing_or_mismatched_advert_never_bypasses_detail_gate(profile, mutation):
    soup = BeautifulSoup(detail(profile), "lxml")
    if mutation == "canonical":
        soup.select_one('link[rel="canonical"]')["href"] = "https://unreviewed.example/job/123"
    else:
        for node in soup.select(".jobdescription, .vacancy-accordion, .content-block-vacancy"):
            node.decompose()
    run, _ = collect_one(profile, str(soup))
    assert not run.items and run.deferred == 1
    assert run.stats[NAMES[profile]]["failure_stage"] == "parse"


@pytest.mark.parametrize("profile", NAMES)
@pytest.mark.parametrize("status", [403, 429])
def test_denied_detail_is_deferred(profile, status):
    run, http = collect_one(profile, error=FetchError("restricted", status=status))
    assert not run.items and run.deferred == 1
    assert len(http.detail_requests) == 1


@pytest.mark.parametrize("status", [403, 429])
def test_denied_later_index_page_stops_detail_requests_for_saved_candidates(status):
    source = config("maastricht")
    listing = pages("maastricht", one=True)
    first = canonical_url(source.opt("url"))
    second = source.opt("url") + "25/?q=&sortColumn=referencedate&sortDirection=desc"
    soup = BeautifulSoup(listing[first], "lxml")
    soup.body.append(BeautifulSoup(f'<ul class="pagination"><li><a href="{second}">2</a></li></ul>', "lxml").ul)
    listing[first] = str(soup)
    http = PageHttp(listing, detail("maastricht"), index_errors={canonical_url(second): FetchError("restricted", status=status)})
    prefs = load_preferences("config/preferences.toml")
    run = asyncio.run(_collect([source], prefs, lambda _: False, http))
    assert len(http.index_requests) == 2
    assert not http.detail_requests
    assert not run.items and run.deferred == 1


@pytest.mark.parametrize("profile", NAMES)
@pytest.mark.parametrize("suffix", ["?alternative=1", "#different", "/more", " "])
def test_unreviewed_job_url_shapes_are_rejected(profile, suffix):
    assert _identity(profile, DETAILS[profile] + suffix) is None


@pytest.mark.parametrize("url", [
    "http://werkenbij.uva.nl/en/vacancies?o=10",
    "https://werkenbij.uva.nl.evil.invalid/en/vacancies?o=10",
    "https://user@werkenbij.uva.nl/en/vacancies?o=10",
    "https://werkenbij.uva.nl/en/vacancies?o=10&o=20",
    "https://werkenbij.uva.nl/en/vacancies?o=250",
    "https://werkenbij.uva.nl/en/vacancies?o=11",
    "https://werkenbij.uva.nl/en/vacancies?keywords=PhD",
])
def test_pagination_accepts_only_reviewed_origin_and_offsets(url):
    assert _listing_key("amsterdam", url) is None


@pytest.mark.parametrize("extra", [
    "<p>Application deadline: 11 January 2027</p>",
    "<p>Application deadline: 11 January</p>",
    "<p>Application deadline: TBD</p>",
    "<div>Application deadline: 11 January 2027</div>",
    "<p>Application deadline: 10 January 2027; domestic applicants: TBD</p>",
    "<p>Application deadline: 10 January 2027; domestic applicants: 11 January</p>",
])
def test_maastricht_listing_date_cannot_hide_alternate_detail_cutoffs(extra):
    soup = BeautifulSoup(detail("maastricht"), "lxml")
    soup.select_one(".jobdescription").append(BeautifulSoup(extra, "lxml").body)
    run, _ = collect_one("maastricht", str(soup))
    assert not run.items and run.deferred == 1


def test_maastricht_reviewed_early_filling_notice_is_not_another_cutoff():
    soup = BeautifulSoup(detail("maastricht"), "lxml")
    soup.select_one(".jobdescription").append(BeautifulSoup(
        "<p>The selection process will start immediately and may close before the application "
        "deadline if a suitable candidate is identified.</p>", "lxml").p)
    run, _ = collect_one("maastricht", str(soup))
    assert len(run.items) == 1 and not run.items[0].hints.get("reject")


@pytest.mark.parametrize("extra", [" for international applicants; domestic applicants: 12 December", " or 12 December 2026", " TBD"])
def test_vienna_scalar_deadline_requires_complete_unqualified_field(extra):
    soup = BeautifulSoup(detail("vienna"), "lxml")
    node = next(n for n in soup.select(".jobdescription p") if "Application deadline:" in n.get_text())
    node.append(extra)
    run, _ = collect_one("vienna", str(soup))
    assert not run.items and run.deferred == 1


def test_amsterdam_other_jobs_deadlines_do_not_change_this_advert():
    soup = BeautifulSoup(detail("amsterdam"), "lxml")
    for node in soup.select("a.vacancy-item .date-metadata"):
        node.string = "01-02-2027"
        node["data-utc"] = "2027-02-01T22:59"
    run, _ = collect_one("amsterdam", str(soup))
    assert len(run.items) == 1 and run.items[0].hints["deadline"] == "2026-11-30"


@pytest.mark.parametrize("mutation", ["title", "date", "id", "yearless", "duplicate_date"])
def test_amsterdam_identity_and_date_representations_must_agree(mutation):
    soup = BeautifulSoup(detail("amsterdam"), "lxml")
    if mutation in {"title", "date"}:
        node = soup.select_one('script[type="application/ld+json"]')
        data = json.loads(node.string)
        data["title" if mutation == "title" else "validThrough"] = "Another role" if mutation == "title" else "2027-01-01"
        node.string = json.dumps(data)
    elif mutation == "id":
        soup.select_one(".vacancy-header .custom-filter04 .metadata-text").string = "99999"
    elif mutation == "yearless":
        soup.select_one(".vacancy-header .date-metadata").string = "30-11"
    else:
        node = copy.copy(soup.select_one(".vacancy-header .date-metadata"))
        node.string, node["data-utc"] = "01-12-2026", "2026-12-01T22:59"
        soup.select_one(".vacancy-header .end-date").append(node)
    run, _ = collect_one("amsterdam", str(soup))
    assert not run.items and run.deferred == 1


@pytest.mark.parametrize("boundary_tag", ["h2", "h3"])
def test_utrecht_faculty_branding_cannot_supply_missing_job_subject(boundary_tag):
    soup = BeautifulSoup(detail("utrecht"), "lxml")
    root = soup.select_one("main #block-primary-content")
    for node in root.select(".content-block-vacancy"):
        node.decompose()
    root.append(BeautifulSoup(f'''<div class="content-block-vacancy"><div class="content-block__inner">
        <h2>Your job</h2><p>Help the team with a participant study, organize schedules,
        maintain files and support careful research documentation.</p>
        <h2>Your qualities</h2><p>Applicants should be reliable, curious, organized and
        comfortable working with colleagues on a substantial research project.</p>
        <{boundary_tag}>About us</{boundary_tag}><p>Our faculty includes economics, finance, law and public policy.</p>
        </div></div>''', "lxml").body)
    for dt in root.select("dt"):
        if dt.get_text(strip=True).startswith("Department"):
            dt.find_next_sibling("dd").string = "Faculty of Law, Economics and Governance"
    run, _ = collect_one("utrecht", str(soup))
    assert len(run.items) == 1
    assert run.items[0].hints["reject"] == "no-field-in-detail"


@pytest.mark.parametrize("profile", ["vienna", "maastricht", "amsterdam"])
def test_benefits_and_general_school_biography_do_not_qualify_advert(profile):
    soup = BeautifulSoup(detail(profile), "lxml")
    if profile == "vienna":
        for h in soup.select(".jobdescription h2"):
            if h.get_text(' ', strip=True).startswith(("Your personal", "Your future", "This is part")):
                parent = h.parent
                for sibling in list(h.next_siblings):
                    sibling.extract()
                parent.append("Work with colleagues on routine research activities, communicate clearly and maintain careful documentation.")
        root = soup.select_one(".jobdescription")
    elif profile == "maastricht":
        root = soup.select_one(".jobdescription")
        # Preserve the matching title/cutoff, but replace job-specific sections.
        root.clear()
        root.append(BeautifulSoup('''<p><strong>What you do</strong></p><p>Work with colleagues on routine research activities, communicate clearly and maintain careful documentation.</p>
        <p><strong>What you bring</strong></p><p>Curiosity, reliability and organization are needed for this substantial research project.</p>
        <p><strong>What we offer</strong></p><p>Our school teaches economics, finance and public policy. Financial benefits are available.</p>
        <p>Application deadline: 10 January 2027</p>''', "lxml").body)
    else:
        for node in soup.select(".vacancy-accordion:has(.accordion-title h2)"):
            heading = node.select_one("h2").get_text()
            node.clear()
            node.append(BeautifulSoup(f'<div class="accordion-title"><h2>{heading}</h2></div><p>Work with colleagues on routine research activities, communicate clearly and maintain careful documentation.</p>', "lxml").body)
        root = soup.body
    root.append(BeautifulSoup('<h2>About the university</h2><p>Our school teaches economics, finance and public policy. Financial benefits are available.</p>', "lxml").body)
    run, _ = collect_one(profile, str(soup))
    assert len(run.items) == 1
    assert run.items[0].hints["reject"] == "no-field-in-detail"
