"""Strict, officially sourced Economics PhD deadline table/heading cases.

All HTML fixtures are local reproductions of university programme layouts;
no manual publication of a discovered date is permitted.
"""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.update_phd_admissions import collect_official_deadline

NOW = datetime(2026, 11, 23, tzinfo=UTC)
UIC = "https://econ.uic.edu/graduate/admissions/application-deadlines/"
BROWN = "https://graduateprograms.brown.edu/graduate-program/economics-phd"


def uic_html(
    domestic: str, international: str, *,
    programme: str = "Ph.D. in Economics",
    intake: str = "Fall 2027 Admission",
    ma_deadline: str = "April 8, 2027",
) -> str:
    filler = "All Ph.D. students must begin the programme in the fall semester. "
    return (
        "<h1>Application Deadlines</h1>"
        f"<h2>{programme}</h2><p>" + filler * 8 + "</p>"
        "<table><tr><th></th><th>" + intake + "</th></tr>"
        f"<tr><th>International applicants</th><td>{international}</td></tr>"
        f"<tr><th>Domestic applicants</th><td>{domestic}</td></tr></table>"
        "<h2>M.A. in Applied Economics</h2>"
        "<table><tr><th>Fall 2027 Admission</th></tr>"
        f"<tr><td>{ma_deadline}</td></tr></table>"
    )


def brown_html(
    deadline_text: str, *, degree: str = "Ph.D.", department: str = "Economics",
) -> str:
    return (
        f"<h1>{department}</h1><p>{degree}</p>"
        f"<p>The {degree} program in {department} trains students to "
        "conduct theoretical and empirical research at the highest level.</p>"
        "<h2>Application Information</h2>"
        "<h3>Application Requirements</h3>"
        "<h4>GRE Subject:</h4><p>Not required</p>"
        "<h4>GRE General:</h4><p>Required</p>"
        "<h3>Dates/Deadlines</h3>"
        "<h4>Application Deadline</h4>"
        "<div>Current-cycle deadline information for doctoral applicants. "
        + ("The graduate programme accepts online applications only. " * 3)
        + f"<span>{deadline_text}</span></div>"
        "<h2>Completion Requirements</h2>"
        "<p>Eight basic courses, advanced research, dissertation.</p>"
    )


class UicDoctoralTableTests(unittest.TestCase):
    def test_full_year_date_in_two_mapped_phd_application_rows_is_verified(self):
        html = uic_html("February 15, 2027", "February 15, 2027")
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=UIC)[:2],
            ("verified", "2027-02-15"),
        )

    def test_separate_domestic_and_international_phd_dates_are_ambiguous(self):
        html = uic_html("February 15, 2027", "March 1, 2027")
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=UIC)[0],
            "ambiguous_deadline",
        )

    def test_masters_date_in_other_section_cannot_change_phd_cutoff(self):
        html = uic_html(
            "February 15, 2027", "February 15, 2027",
            ma_deadline="April 25, 2027",
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=UIC)[:2],
            ("verified", "2027-02-15"),
        )

    def test_masters_only_heading_is_not_economics_phd_evidence(self):
        html = uic_html(
            "February 15, 2027", "February 15, 2027",
            programme="M.A. in Applied Economics",
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=UIC)[0],
            "verified",
        )

    def test_other_doctoral_subject_is_not_economics_phd(self):
        html = uic_html(
            "February 15, 2027", "February 15, 2027",
            programme="Ph.D. in Sociology",
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=UIC)[0],
            "verified",
        )

    def test_yearless_phd_application_rows_remain_unverified(self):
        html = uic_html("February 15", "February 15")
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=UIC)[0],
            "verified",
        )

    def test_unmatched_intake_cycle_does_not_verify_future_date(self):
        html = uic_html(
            "February 15, 2027", "February 15, 2027",
            intake="Fall 2026 Admission",
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=UIC)[0],
            "verified",
        )

    def test_missing_domestic_date_stays_unverified(self):
        html = uic_html("", "February 15, 2027")
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=UIC)[0],
            "verified",
        )

    def test_identical_table_on_unrelated_host_cannot_verify(self):
        html = uic_html("February 15, 2027", "February 15, 2027")
        self.assertNotEqual(
            collect_official_deadline(
                html, now=NOW,
                source_url="https://economics.example.edu/graduate/admissions/application-deadlines/",
            )[0],
            "verified",
        )


class BrownDoctoralDirectoryHeadingTests(unittest.TestCase):
    def test_dated_application_heading_separate_from_value_still_verifies(self):
        html = brown_html("January 1, 2027")
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=BROWN)[:2],
            ("verified", "2027-01-01"),
        )

    def test_yearless_application_heading_is_not_current_cycle_proof(self):
        html = brown_html("January 1")
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=BROWN)[0],
            "verified",
        )

    def test_masters_directory_does_not_inherit_phd_application_heading(self):
        html = brown_html("January 1, 2027", degree="M.A.")
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=BROWN)[0],
            "verified",
        )

    def test_separate_doctoral_deadline_dates_remain_ambiguous(self):
        html = brown_html("January 1, 2027 or January 15, 2027")
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=BROWN)[0],
            "ambiguous_deadline",
        )

    def test_other_department_h1_does_not_inherit_economics_date(self):
        html = brown_html("January 1, 2027", department="Sociology")
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=BROWN)[0],
            "verified",
        )

    def test_date_after_completion_requirements_is_not_application_deadline(self):
        html = brown_html("not announced") + "<p>January 1, 2027</p>"
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=BROWN)[0],
            "verified",
        )


if __name__ == "__main__":
    unittest.main()
