"""Replay employer structures and prove that school branding cannot qualify jobs."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import httpx
import pytest
from bs4 import BeautifulSoup

from predoc_pipeline.boards.collector import _collect, _scrape_all
from predoc_pipeline.boards.config import load_board_sources, load_preferences
from predoc_pipeline.boards.filter import RelevanceFilter
from predoc_pipeline.boards.http import FetchError
from predoc_pipeline.boards.models import JobPostSchema
from predoc_pipeline.boards.scrapers import SCRAPERS
from predoc_pipeline.boards.scrapers.official_research import OfficialResearchScraper
from predoc_pipeline.core.health import public_failure, source_status

FIXTURES = Path("tests/fixtures/boards/official_research_20261124")
NAMES = {"esmt": "esmt_berlin_research", "isb": "isb_academic_research",
         "wu": "wu_vienna_research"}
DETAILS = {
    "esmt": "https://jobs.esmt.berlin/de?id=63a5b3",
    "isb": "https://www.isb.edu/work-at-isb/academic-openings/"
           "research-associate-with-professor-bhavna-rai",
    "wu": "https://jobs.wu.ac.at/Research-and-Teaching-Assistant-eng-j2961.html",
}
CARDS = {"esmt": ".portlet.light.bordered", "isb": ".isb-link-items__cta",
         "wu": "article.joboffer_container"}


@pytest.fixture(autouse=True)
def fixed_date(monkeypatch):
    monkeypatch.setattr("predoc_pipeline.boards.filter.today", lambda: date(2026, 11, 24))
    monkeypatch.setattr("predoc_pipeline.boards.heuristics._today", lambda: date(2026, 11, 24))
    monkeypatch.setattr("predoc_pipeline.boards.scrapers.official_research.today", lambda: date(2026, 11, 24))


def config(profile):
    return next(s for s in load_board_sources("config/sources.toml") if s.name == NAMES[profile])


def page(profile, *, one=False, job_url=None):
    html = (FIXTURES / f"{profile}_listing.html").read_text()
    if not one:
        return html
    soup = BeautifulSoup(html, "lxml")
    for card in soup.select(CARDS[profile]):
        anchor = card if card.name == "a" else card.select_one("a[href]")
        if urljoin(config(profile).opt("url"), anchor["href"]) != (job_url or DETAILS[profile]):
            card.decompose()
    return str(soup)


def detail(profile):
    return (FIXTURES / f"{profile}_detail.html").read_text()


class PageHttp:
    def __init__(self, listing, body="", *, final_url=None, error=None):
        self.listing, self.body = listing, body
        self.final_url, self.error = final_url, error
        self.requests = []

    def set_host_interval(self, url, seconds):
        assert url.startswith("https://") and seconds >= 1.5

    async def get_text(self, url):
        return self.listing

    async def request(self, method, url):
        self.requests.append(url)
        if self.error:
            raise self.error
        return httpx.Response(
            200, text=self.body,
            request=httpx.Request(method, self.final_url or url),
        )


def discover(profile, html=None):
    source = config(profile)
    scraper = OfficialResearchScraper(source, PageHttp(html if html is not None else page(profile)))
    return asyncio.run(_scrape_all([scraper], 1, 5))[0]


def collect_one(profile, body=None, *, final_url=None, error=None, fetch_details=True, job_url=None):
    http = PageHttp(page(profile, one=True, job_url=job_url), detail(profile) if body is None else body,
                    final_url=final_url, error=error)
    prefs = load_preferences("config/preferences.toml")
    prefs.enrich.fetch_details = fetch_details
    run = asyncio.run(_collect([config(profile)], prefs, lambda _: False, http))
    return run, http


@pytest.mark.parametrize(("profile", "count"), [("esmt", 2), ("isb", 13), ("wu", 6)])
def test_observed_indexes_keep_research_jobs_and_exclude_faculty_admin_teaching(profile, count):
    cfg = config(profile)
    assert cfg.enabled and not cfg.field_implied and not cfg.may_be_empty
    assert SCRAPERS[cfg.type] is OfficialResearchScraper
    result = discover(profile)
    assert result.ok
    assert len(result.posts) == count
    assert len({p.url for p in result.posts}) == count
    assert all(not p.field_implied for p in result.posts)
    assert all(p.extra["official_requisition_id"] for p in result.posts)
    assert not any("Academic Associate" in p.title or "Assistant Professor" in p.title
                   or "eDeveloper" in p.title or "IT-Manager" in p.title
                   or "Controller" in p.title for p in result.posts)
    assert source_status(result.as_stats()) == "successful"


def test_wu_same_title_keeps_distinct_requisitions_and_actual_department():
    posts = discover("wu").posts
    associates = [p for p in posts if p.title == "Research and Teaching Associate"]
    assert {p.extra["official_requisition_id"] for p in associates} == {"2966", "2967"}
    assert {p.institution for p in posts} == {"WU Vienna"}
    assert {p.department for p in associates} == {"Department of Business Analytics and Decision Sciences"}


@pytest.mark.parametrize("profile", NAMES)
def test_matching_official_details_survive_full_collector_with_no_navigation_text(profile):
    run, http = collect_one(profile)
    assert run.deferred == 0 and run.rejected == {}
    assert len(run.items) == 1
    assert run.items[0].hints["enriched"] is True
    assert run.items[0].hints["field_implied"] is False
    assert "Navigation" not in run.items[0].text
    assert "Business school footer" not in run.items[0].text
    assert http.requests == [DETAILS[profile]]
    assert source_status(run.stats[NAMES[profile]]) == "successful"


def test_wu_employer_branding_is_absent_from_subject_evidence():
    run, _ = collect_one("wu")
    text = run.items[0].text
    assert "business and economics universities" not in text
    assert "University of Economics and Business" not in text
    assert "Political Economy of Public Policy" in text
    assert run.items[0].hints["deadline"] == "2026-12-09"


def test_wu_german_application_deadline_is_bound_to_explicit_full_year_and_requisition():
    body = (FIXTURES / "wu_german_detail.html").read_text()
    url = "https://jobs.wu.ac.at/Universitaetsassistentin-prae-doc-de-j2950.html"
    run, _ = collect_one("wu", body, job_url=url)
    assert len(run.items) == 1 and run.rejected == {}
    assert run.items[0].hints["deadline"] == "2026-11-25"
    assert "Wirtschaftsuniversitäten" not in run.items[0].text


@pytest.mark.parametrize("change", ["missing_year", "wrong_id", "conflict", "partial_second"])
def test_wu_german_partial_conflicting_or_mismatched_application_dates_defer(change):
    body = (FIXTURES / "wu_german_detail.html").read_text()
    url = "https://jobs.wu.ac.at/Universitaetsassistentin-prae-doc-de-j2950.html"
    if change == "missing_year":
        body = body.replace("25.11.2026", "25.11.")
    elif change == "wrong_id":
        body = body.replace("Kennzahl: 2950", "Kennzahl: 9999")
    else:
        second = "26.11.2026" if change == "conflict" else "26.11."
        body = body.replace("Wir freuen uns auf Sie!", "bewerben Sie sich bitte bis spätestens "
                            + second + " (Kennzahl: 2950).")
    run, _ = collect_one("wu", body, job_url=url)
    assert run.items == [] and run.deferred == 1


@pytest.mark.parametrize("profile", NAMES)
@pytest.mark.parametrize("changed", ["empty", "different_title", "navigation_only"])
def test_missing_or_mismatched_detail_is_deferred_with_visible_source_failure(profile, changed):
    body = detail(profile)
    if changed == "empty":
        body = ""
    elif changed == "different_title":
        soup = BeautifulSoup(body, "lxml")
        heading = soup.select_one("h2.isb-tier-banner__title") if profile == "isb" else soup.h1
        heading.string = "Unrelated vacancy with a different title"
        body = str(soup)
    else:
        body = "<nav>Research Assistant in Economics and Finance</nav><main>Welcome</main>"
    run, _ = collect_one(profile, body)
    assert run.items == [] and run.deferred == 1
    stats = run.stats[NAMES[profile]]
    assert not stats["ok"] and stats["errors"] == 1
    assert stats["new"] == 0 and stats["failure_counts"]["parse"] == 1
    assert "deferred" in stats["messages"][0]
    assert source_status(stats) == "partial"


@pytest.mark.parametrize("profile", NAMES)
def test_fetch_failure_and_disabled_enrichment_cannot_publish_strong_title(profile):
    for options in ({"error": FetchError("HTTP 503", 503)}, {"fetch_details": False}):
        run, _ = collect_one(profile, **options)
        assert run.items == [] and run.deferred == 1
        assert run.stats[NAMES[profile]]["failure_counts"]["fetch"] == 1


@pytest.mark.parametrize("status", [404, 410])
def test_removed_advert_keeps_existing_closed_verdict(status):
    run, _ = collect_one("esmt", error=FetchError(f"HTTP {status}", status))
    assert run.deferred == 0
    assert run.rejected == {"filled-or-closed": 1}
    assert len(run.items) == 1
    assert run.items[0].hints["reject"] == "filled-or-closed"


@pytest.mark.parametrize("status", [403, 429])
def test_provider_denial_stops_later_detail_requests(status):
    http = PageHttp(page("esmt"), error=FetchError(f"HTTP {status}", status))
    prefs = load_preferences("config/preferences.toml")
    run = asyncio.run(_collect([config("esmt")], prefs, lambda _: False, http))
    assert len(http.requests) == 1
    assert run.items == [] and run.deferred == 2
    assert run.stats[NAMES["esmt"]]["failure_counts"]["fetch"] == 2


@pytest.mark.parametrize("profile", NAMES)
def test_unexpected_redirect_never_uses_other_job_or_host(profile):
    for target in ("https://example.org/jobs/123", config(profile).opt("url"),
                   DETAILS[profile].replace("2961", "2967").replace("63a5b3", "f47b7c")
                   .replace("bhavna-rai", "abhinav-uppal")):
        run, _ = collect_one(profile, final_url=target)
        assert run.items == [] and run.deferred == 1


@pytest.mark.parametrize("profile", ["esmt", "wu"])
def test_canonical_identity_must_match_and_be_unique(profile):
    for body in (
        detail(profile).replace(DETAILS[profile], DETAILS[profile].replace("2961", "2967")
                                .replace("63a5b3", "f47b7c")),
        detail(profile).replace('<link rel="canonical"', '<link rel="alternate"'),
        detail(profile).replace("</head>", f'<link rel="canonical" href="{DETAILS[profile]}"></head>'),
    ):
        run, _ = collect_one(profile, body)
        assert run.items == [] and run.deferred == 1


@pytest.mark.parametrize("profile", NAMES)
def test_wrong_field_advert_cannot_be_rescued_by_school_navigation(profile):
    soup = BeautifulSoup(detail(profile), "lxml")
    if profile == "esmt":
        sections = soup.select(".description-anchor-color")
    elif profile == "isb":
        sections = soup.select(".isb-richtext__content")
    else:
        sections = soup.select(".scheme-introduction, .scheme-task, .scheme-profile, .scheme-contact")
    for section in sections:
        heading = section.select_one("h2")
        heading = heading.extract() if heading else None
        section.clear()
        if heading:
            section.append(heading)
        if profile == "wu" and "scheme-introduction" in section.get("class", []):
            unit = soup.new_tag("strong")
            unit.string = "Institute for Computer Science"
            section.append(unit)
        section.append("Conduct computer science and robotics research, maintain engineering systems, "
                       "and develop software for laboratory automation. Computer science qualifications "
                       "and robotics research experience are required for this technical research role.")
    run, _ = collect_one(profile, str(soup))
    assert run.rejected == {"wrong-field-detail": 1}
    assert run.items[0].hints["reject"] == "wrong-field-detail"


def test_wu_unknown_subject_is_not_economics_just_because_branding_says_so():
    soup = BeautifulSoup(detail("wu"), "lxml")
    for section in soup.select(".scheme-introduction, .scheme-task, .scheme-profile, .scheme-contact"):
        section.clear()
        if "scheme-introduction" in section.get("class", []):
            unit = soup.new_tag("strong")
            unit.string = "Institute for Applied Research"
            section.append(unit)
        section.append("Carry out research tasks and prepare materials for teaching. Applicants should "
                       "be organised, communicate clearly and demonstrate strong analytical skills. "
                       "The specific subject and qualification area have not been provided.")
    run, _ = collect_one("wu", str(soup))
    assert run.rejected == {"no-field-in-detail": 1}


@pytest.mark.parametrize(("location", "country", "region", "basis"), [
    (None, "India", "Other", "reviewed_isb_profile"),
    ("Hyderabad / Mohali", "India", "Other", "advert_label"),
    ("Toronto, Canada", "Canada", "Canada", "advert_label"),
])
def test_isb_edu_domain_cannot_replace_india_profile_or_explicit_job_location(
    location, country, region, basis,
):
    soup = BeautifulSoup(detail("isb"), "lxml")
    if location:
        paragraph = soup.new_tag("p")
        paragraph.string = "Location: " + location
        soup.select_one(".isb-richtext__content").append(paragraph)
    run, _ = collect_one("isb", str(soup))
    assert run.items[0].hints["country"] == country
    assert run.items[0].hints["region"] == region
    assert run.items[0].hints["country_basis"] == basis


@pytest.mark.parametrize("tag", ["span", "p", "div"])
def test_wu_welcome_boilerplate_never_counts_even_when_markup_or_prefix_changes(tag):
    soup = BeautifulSoup(detail("wu"), "lxml")
    intro = soup.select_one(".scheme-introduction")
    intro.clear()
    welcome = soup.new_tag(tag)
    welcome.string = ("Welcome to one of Europe's largest business and economics universities. "
                      "Our university offers outstanding business opportunities.")
    intro.append(welcome)
    unit = soup.new_tag("strong")
    unit.string = "Institute for Applied Research"
    intro.append(unit)
    for section in soup.select(".scheme-task, .scheme-profile"):
        section.clear()
        section.append("Support research projects and teaching activities. Applicants need to be "
                       "well organised, communicate clearly, document results and collaborate "
                       "with colleagues. This advert does not identify a particular subject area.")
    run, _ = collect_one("wu", str(soup))
    assert run.rejected == {"no-field-in-detail": 1}
    assert "business and economics universities" not in run.items[0].text


@pytest.mark.parametrize(("profile", "extra_html"), [
    ("isb", '<div class="isb-richtext__content"><h2>About ISB</h2>'
     '<p>The Indian School of Business evolved from the need for a world-class business school '
     'in Asia and anticipated the leadership needs of the emerging Asian economies.</p></div>'
     '<div class="isb-richtext__content"><h2>Research Summary of the Faculty</h2>'
     '<p>The Indian School of Business aims to train researchers across Accounting, Finance, '
     'Economics and Public Policy, Information Systems, Marketing and Operations Management.</p></div>'),
    ("esmt", '<div class="description-anchor-color"><h2>Why you will love working with us</h2>'
     '<p>Financial Benefits. ESMT Berlin is a leading global business school. '
     'Enjoy financial benefits, support and a welcoming business school community.</p></div>'),
])
def test_school_biography_and_employee_benefits_do_not_supply_subject_evidence(profile, extra_html):
    soup = BeautifulSoup(detail(profile), "lxml")
    selector = ".isb-richtext__content" if profile == "isb" else ".description-anchor-color"
    for section in soup.select(selector):
        heading = section.h2.extract()
        section.clear()
        section.append(heading)
        section.append("Assist colleagues with research projects, document results, organise source "
                       "materials and communicate clearly. The role calls for analytical skills "
                       "and good organisation but does not specify the research subject.")
    root = soup.select_one("main.inner-page") if profile == "isb" else soup.select_one(".container")
    for node in list(BeautifulSoup(extra_html, "lxml").body.children):
        root.append(node)
    run, _ = collect_one(profile, str(soup))
    assert run.rejected == {"no-field-in-detail": 1}


@pytest.mark.parametrize("label", ["Start Date: August 24, 2026", "The expected date of joining is November 10, 2025"])
def test_isb_elapsed_start_is_deferred_without_asserting_closed(label):
    soup = BeautifulSoup(detail("isb"), "lxml")
    paragraph = soup.new_tag("p")
    paragraph.string = label
    soup.select_one(".isb-richtext__content").append(paragraph)
    run, _ = collect_one("isb", str(soup))
    assert run.items == [] and run.deferred == 1 and run.rejected == {}
    assert "elapsed start" in run.stats[NAMES["isb"]]["messages"][0]


def test_public_unverified_advert_messages_are_clear_and_do_not_copy_exception_text():
    assert public_failure("Official advert has an elapsed start; candidate deferred") == (
        "Advert start date has passed; current recruitment unconfirmed"
    )
    assert public_failure("Official advert detail unverified; candidate deferred https://secret.test") == (
        "Advert detail could not be corroborated; candidate deferred"
    )


@pytest.mark.parametrize("profile", NAMES)
def test_missing_listing_cards_and_changed_heading_are_not_healthy_empty(profile):
    soup = BeautifulSoup(page(profile), "lxml")
    for card in soup.select(CARDS[profile]):
        card.decompose()
    result = discover(profile, str(soup))
    assert not result.ok and source_status(result.as_stats()) == "failed"
    result = discover(profile, page(profile).replace(str(soup.h1), "<h1>Welcome home</h1>"))
    assert not result.ok


def test_wu_requisition_mismatch_is_visible_partial_parse_failure():
    changed = page("wu").replace("2966 - Department", "9999 - Department")
    result = discover("wu", changed)
    assert not result.ok and len(result.posts) == 5
    assert result.failure_stage == "parse"
    assert "2966" not in {p.extra["official_requisition_id"] for p in result.posts}


def test_conflicting_duplicate_requisition_is_not_arbitrarily_selected():
    soup = BeautifulSoup(page("esmt", one=True), "lxml")
    duplicate = BeautifulSoup(str(soup.select_one(CARDS["esmt"])), "lxml")
    duplicate.h2.string = "Postdoctoral Researcher (Other Center)"
    soup.main.append(duplicate.select_one(CARDS["esmt"]))
    result = discover("esmt", str(soup))
    assert result.posts == [] and not result.ok


def test_new_unreviewed_pagination_is_reported_as_partial():
    html = page("isb") + '<a rel="next" href="?page=2">Next</a>'
    result = discover("isb", html)
    assert len(result.posts) == 13 and not result.ok
    assert result.failure_stage == "limit"


@pytest.mark.parametrize("title", [
    "Research Associate with Professor Bhavna Rai",
    "Research Associate position under Professor Sumeet Kumar",
    "Research Associate Position under Professor. Shekhar Tomar",
])
def test_isb_supervisor_introducer_is_not_a_faculty_job(title):
    flt = RelevanceFilter(load_preferences("config/preferences.toml").filters)
    post = JobPostSchema(title=title, source=NAMES["isb"], url=DETAILS["isb"],
                         institution="Indian School of Business")
    assert flt.evaluate(post).keep
    post.source = "legacy_source"
    assert flt.evaluate(post).reason == "excluded-title"


@pytest.mark.parametrize("title", [
    "Research Associate Professor in Economics",
    "Assistant Professor in Economics",
    "Research Associate with Professor Smith — Faculty Position",
    "Research Associate with Professor Smith — Senior Lecturer",
])
def test_isb_real_faculty_and_other_excluded_words_remain_rejected(title):
    flt = RelevanceFilter(load_preferences("config/preferences.toml").filters)
    post = JobPostSchema(title=title, source=NAMES["isb"], url=DETAILS["isb"],
                         institution="Indian School of Business")
    assert flt.evaluate(post).reason == "excluded-title"


def test_existing_best_effort_sources_do_not_opt_into_detail_requirement():
    cfg = config("esmt").model_copy(update={"type": "link_scan", "name": "legacy_source"})
    cfg.model_extra.update({"link_pattern": r"/de\?id=", "title_allow_pattern": "Predoctoral"})
    prefs = load_preferences("config/preferences.toml")
    prefs.enrich.fetch_details = False
    http = PageHttp('<a href="https://jobs.esmt.berlin/de?id=63a5b3">Predoctoral Researcher in Economics</a>')
    run = asyncio.run(_collect([cfg], prefs, lambda _: False, http))
    assert len(run.items) == 1 and run.deferred == 0
