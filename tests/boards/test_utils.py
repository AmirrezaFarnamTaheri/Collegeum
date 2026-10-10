from datetime import date

import pytest

from predoc_pipeline.boards.utils.dates import extract_deadline, parse_date, parse_posted
from predoc_pipeline.boards.utils.geo import detect_location
from predoc_pipeline.boards.utils.text import (
    canonical_url,
    normalize_title,
    split_role_at_institution,
)

REF = date(2026, 9, 24)


@pytest.mark.parametrize("text,expected", [
    ("Deadline: 20th April 2027", date(2027, 4, 20)),
    ("Closing date: 01 Oct", date(2026, 10, 1)),
    ("Application deadline: 31.10.2026", date(2026, 10, 31)),
    ("Deadline: First review date October 7, 2026, then rolling", None),
    ("Applications close on 15 November 2026.", date(2026, 11, 15)),
    ("Closes: 28th November 2026", date(2026, 11, 28)),
    ("Last application date 2026-10-15", date(2026, 10, 15)),
    ("Deadline 13 Oct 2026 - 23:00 (Europe/Oslo)", date(2026, 10, 13)),
    ("Sista ansökningsdag: 15 oktober 2026", date(2026, 10, 15)),
])
def test_extract_deadline(text, expected):
    d, raw = extract_deadline(text, REF)
    assert d == expected, raw


def test_rolling_deadline():
    assert extract_deadline("Deadline: Rolling", REF) == (None, "Rolling")


def test_no_false_deadline_from_salary_or_ids():
    assert extract_deadline("Salary £38,000 per annum, ref JR25579, grade 6", REF) == (None, None)


def test_us_style_numeric_is_swapped_when_impossible():
    assert parse_date("Thu, 09/24/2026 - 10:45", REF) == date(2026, 9, 24)


@pytest.mark.parametrize("text,days", [("Posted Today", 0), ("Posted Yesterday", 1),
                                       ("Posted 3 Days Ago", 3), ("Posted 30+ Days Ago", 30),
                                       ("2 weeks ago", 14)])
def test_parse_posted(text, days):
    assert (REF - parse_posted(text, REF)).days == days


def test_title_normalisation_merges_predoc_spellings():
    assert normalize_title("Pre-Doctoral RA (m/f/d)") == normalize_title("predoctoral ra")


def test_canonical_url_strips_tracking_and_linkedin_slug():
    assert canonical_url("https://uk.linkedin.com/jobs/view/predoc-at-oxford-4012345678?refId=x&trackingId=y") \
        == "https://www.linkedin.com/jobs/view/4012345678"
    assert canonical_url("https://Example.org/job/1/?utm_source=x&id=5#top") == "https://example.org/job/1?id=5"


def test_split_role_at_institution():
    assert split_role_at_institution("Predoctoral RA in Dev Econ at London School of Economics (UK)") == \
        ("Predoctoral RA in Dev Econ", "London School of Economics", "UK")


@pytest.mark.parametrize("text,region", [
    ("Universitat Pompeu Fabra, Barcelona, Spain", "Europe"),
    ("UCL School of Management, University College London", "UK"),
    ("Columbia University, School of International and Public Affairs", "US"),
    ("University of British Columbia", "Canada"),
    ("London, ON", "Canada"),
    ("Cambridge, MA", "US"),
    ("University of Cambridge", "UK"),
    ("Byblos, Lebanon", "Other"),
])
def test_geo(text, region):
    assert detect_location(text)[1] == region


def test_geo_ignores_german_mit():
    assert detect_location("Bewerbung mit Lebenslauf bis 30.09.") == (None, None)


def test_two_digit_us_dates():
    assert parse_date("Deadline/First Review Date: 5/24/26", REF) == date(2026, 5, 24)


def test_year_not_stated_is_flagged():
    from predoc_pipeline.publish.telegram import deadline_label
    assert "year not stated" in deadline_label("2027-02-28T23:59:59Z", "Feb 28")
    assert deadline_label("2027-02-28T23:59:59Z", "Deadline: 28 February 2027").startswith("28 Feb 2027")
    assert deadline_label(None, "Rolling basis") == "rolling"
