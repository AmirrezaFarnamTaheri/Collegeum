from datetime import date

import pytest

from predoc_pipeline.boards.config import load_preferences
from predoc_pipeline.boards.filter import RelevanceFilter
from predoc_pipeline.boards.models import JobPostSchema
from tests.boards.conftest import ROOT

FLT = RelevanceFilter(load_preferences(ROOT / "config" / "preferences.toml").filters)


def post(title, **kw):
    kw.setdefault("url", "https://example.org/" + title.replace(" ", "-"))
    kw.setdefault("source", "test")
    return JobPostSchema(title=title, **kw)


@pytest.mark.parametrize("title,kw", [
    ("Pre-Doctoral Research Assistant", {}),
    ("Predoc in Macroeconomics", {}),
    ("Research Assistant in Economics", {}),
    ("Research Assistant", {"department": "Department of Economics"}),
    ("Research Analyst - Finance Group", {}),
    ("Full-Time Research Professional (pre-doctoral)", {}),
    ("Research Assistant", {"field_implied": True}),
])
def test_keeps_relevant(title, kw):
    v = FLT.evaluate(post(title, **kw))
    assert v.keep, v.reason


def test_predoc_without_field_is_checked_on_detail_page():
    # "predoctoral" is also common in biomedical labs, so the field is verified later
    v = FLT.evaluate(post("Pre-Doctoral Research Assistant"))
    assert v.keep and v.needs_field_check and v.score >= 50
    assert not FLT.evaluate(post("Predoc in Macroeconomics")).needs_field_check


@pytest.mark.parametrize("title,reason", [
    ("Postdoctoral Fellow in Economics", "excluded-title"),
    ("Assistant Professor in Health Economics", "excluded-title"),
    ("PhD student in Economics", "phd-position"),
    ("Doctoral candidate in finance", "phd-position"),
    ("Lab Manager", "no-role-term"),
    ("Summer School in Econometrics", "excluded-title"),
])
def test_rejects(title, reason):
    v = FLT.evaluate(post(title))
    assert not v.keep and v.reason == reason


def test_role_without_field_is_deferred_to_detail_page():
    v = FLT.evaluate(post("Research Assistant/Technician 3"))
    assert v.keep and v.needs_field_check


def test_pre_phd_is_not_a_phd_position():
    assert FLT.evaluate(post("Research Fellow (pre-PhD) in Economics")).keep


def test_expired_and_stale():
    assert FLT.evaluate(post("Predoc RA in economics", deadline=date(2026, 9, 1))).reason == "expired"
    assert FLT.evaluate(post("Predoc RA in economics", date_posted=date(2025, 1, 1))).reason == "stale"


def test_social_post_needs_hiring_cue():
    congrats = post("Congrats to our predocs on their PhD admissions in economics!",
                    description_snippet="Congrats to our predocs on their PhD admissions in economics!",
                    extra={"social": True})
    hiring = post("We're hiring a predoc in economics at UCL",
                  description_snippet="We're hiring a predoc in economics at UCL. Apply by Nov 1",
                  extra={"social": True})
    assert not FLT.evaluate(congrats).keep
    assert FLT.evaluate(hiring).keep


def test_region_gate():
    us = post("Predoctoral RA", institution="Columbia Business School")
    assert FLT.assign_region(us) is True
    assert FLT.region_ok(us) == (False, "region-US")
    eu = post("Predoctoral RA", institution="Universitat Pompeu Fabra, Barcelona, Spain")
    FLT.assign_region(eu)
    assert FLT.region_ok(eu) == (True, None)
    unknown = post("Predoctoral RA")
    assert FLT.assign_region(unknown) is False
    assert FLT.region_ok(unknown) == (True, None)
    # a place named only in the title never causes a drop
    guessed = post("Predoctoral RA on Rwanda education data")
    assert FLT.assign_region(guessed) is False
    assert guessed.region is None and guessed.extra["region_guess"] == "Other"
    assert FLT.region_ok(guessed)[0]


def test_strong_flag_only_for_predoc_terms():
    assert FLT.evaluate(post("Pre-doctoral Research Assistant")).strong
    assert not FLT.evaluate(post("Research Assistant in Economics")).strong


@pytest.mark.parametrize("title,kw,keep", [
    ("Pre-Doctoral Research Associate", {"fields_of_research": "Developmental psychology, clinical psychology"}, False),
    ("Predoctoral Research Assistant in Neuroscience", {}, False),
    ("Research Assistant", {"department": "Department of Chemistry"}, False),
    ("Research Assistant in Biomedical Engineering", {}, False),
    ("Pre-doctoral Researcher in Health Economics and Clinical Trials", {}, True),   # econ wins
    ("Research Assistant in Marketing", {}, True),
    ("Research Assistant", {"department": "Faculty of Law"}, True),
    ("Predoc - Political Science", {}, True),
    ("Pre-Doctoral Fellow", {"fields_of_research": "Microeconomics, Behavioral Economics"}, True),
])
def test_field_preferences(title, kw, keep):
    v = FLT.evaluate(post(title, **kw))
    assert v.keep is keep, v.reason


def test_field_verdict_on_long_pages():
    assert FLT.field_verdict_long("The lab studies protein folding; cell culture and PCR.") == "unwanted"
    assert FLT.field_verdict_long("Department of Economics. Work on labour economics and public finance.") == "wanted"
    assert FLT.field_verdict_long("Join our friendly team in a great city.") == "unknown"


@pytest.mark.parametrize("title,inst", [
    ("Research Associate, Semiconductors & AI Infrastructure - 26229", "Enverus"),
    ("Research Analyst", "Cushman & Wakefield"),
    ("Event Driven Research Analyst", "Susquehanna International Group"),
    ("Equity Research Associate - Metals & Mining", "Canaccord Genuity Group Inc."),
    ("Equity Research Associate, Paper & Forest Products", "TD Securities"),
    ("Research Analyst in Economics", "Bank of Canada"),
    ("Predoctoral Research Associate - Development Economics", "J-PAL Europe"),
])
def test_industry_banks_and_jpal_are_dropped(title, inst):
    v = FLT.evaluate(post(title, institution=inst, extra={"employer_required": True}))
    assert not v.keep, v


@pytest.mark.parametrize("title,inst", [
    ("Predoctoral Research Assistant", "University of Oxford"),
    ("Pre-doctoral fellow in economics", "London School of Economics and Political Science (LSE)"),
    ("Research Assistant in Economics", "IESE Business School"),
    ("Pre-Doctoral Research Associate: Strategy", "INSEAD"),
    ("Research Assistant (pre-doc) in economics", "CEMFI"),
    ("Research Assistant in economics", "Kiel Institute for the World Economy"),
    ("Pre-doc in finance", "WU Vienna University of Economics and Business"),
])
def test_academic_employers_are_kept(title, inst):
    v = FLT.evaluate(post(title, institution=inst, extra={"employer_required": True}))
    assert v.keep, v.reason


def test_unknown_employer_only_matters_where_required():
    assert not FLT.evaluate(post("Research Assistant in economics", extra={"employer_required": True})).keep
    assert FLT.evaluate(post("Research Assistant in economics")).keep


def test_jpal_url_is_banned_even_without_name():
    p = post("Predoctoral Research Associate in economics", url="https://www.povertyactionlab.org/careers/x-job-1")
    assert FLT.evaluate(p).reason == "excluded-employer"


def test_arts_media_jobs_are_dropped():
    v = FLT.evaluate(post("Research Trainee - Arts Desk", institution="The Institute of Art and Ideas",
                          extra={"employer_required": True}))
    assert not v.keep and v.reason == "wrong-field"


def test_everyday_words_alone_do_not_prove_the_field():
    assert FLT.field_verdict_long("Join our team. We work on policy and government projects in business.") == "unknown"
    assert FLT.field_verdict_long("Vancouver School of Economics: research assistant for labour economics.") == "wanted"
    # ...but in a title or department they still count
    assert FLT.evaluate(post("Research Assistant", department="Faculty of Law")).keep
