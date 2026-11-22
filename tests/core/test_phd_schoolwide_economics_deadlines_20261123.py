"""Schoolwide official doctoral application windows covering Economics.

Fictional HTML fixtures model university-owned shared application pages.
A shared cutoff is admissible only when the page explicitly covers the
named economics doctoral route, not merely a general graduate programme.
"""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.update_phd_admissions import collect_official_deadline

NOW = datetime(2026, 11, 23, tzinfo=UTC)
PURDUE = "https://business.purdue.edu/phd/admissions.php"
WHARTON = "https://doctoral.wharton.upenn.edu/application-requirements/"


def purdue(admissions: str, *, economics: bool = True, doctoral: bool = True) -> str:
    return (
        "<h1>Admissions</h1>"
        '<nav><a href="/phd/economics">Economics</a>'
        '<a href="/phd/finance">Finance</a></nav>' if economics else
        "<h1>Admissions</h1><nav><a href='/phd/finance'>Finance</a></nav>"
    ) + (
        "<p>Admission to Daniels School of Business doctoral programs is "
        "limited to students of outstanding promise.</p>" if doctoral else
        "<p>Admission to the MBA program is competitive.</p>"
    ) + (
        "<h2>Application Deadlines</h2>"
        "<p>The graduate application and all supplemental materials "
        "must be received by this date to be considered for review.</p>"
        + admissions
        + "<h2>Application Requirements</h2>"
        "<p>Economics applicants must submit a GRE score. "
        "All other applicants may submit GRE or GMAT.</p>"
    )


def wharton(deadline: str, *, applied_econ: bool = True, doctoral: bool = True) -> str:
    links = (
        "<nav><a href='/programs/applied-economics'>Applied Economics</a>"
        "<a href='/programs/finance'>Finance</a></nav>"
        if applied_econ else
        "<nav><a href='/programs/finance'>Finance</a></nav>"
    )
    scope = (
        "<p>Wharton Doctoral Programs requires ALL applicants to submit GRE "
        "or GMAT scores depending on programme.</p>"
        if doctoral else
        "<p>Wharton MBA Admissions accepts applicants.</p>"
    )
    return (
        "<h1>Application Requirements</h1>" + links
        + "<h2>Application Deadline</h2><p>" + deadline + "</p>"
        + scope
        + ("<p>Applied Economics: GRE only.</p>" if applied_econ else "")
    )


class SchoolwideOfficialDoctoralDeadlineTests(unittest.TestCase):
    def test_purdue_economics_programme_inherits_explicit_schoolwide_phd_cutoff(self):
        html = purdue("<p>Fall 2027</p><p>January 15, 2027</p>")
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=PURDUE)[:2],
            ("verified", "2027-01-15"),
        )

    def test_purdue_economics_loses_scope_without_economics_programme_link(self):
        html = purdue(
            "<p>Fall 2027</p><p>January 15, 2027</p>", economics=False,
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=PURDUE)[0],
            "verified",
        )

    def test_purdue_mba_cutoff_is_not_a_phd_cutoff(self):
        html = purdue(
            "<p>Fall 2027</p><p>January 15, 2027</p>", doctoral=False,
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=PURDUE)[0],
            "verified",
        )

    def test_purdue_yearless_cycle_is_not_a_confirmed_date(self):
        html = purdue("<p>Fall 2027</p><p>January 15</p>")
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=PURDUE)[0],
            "verified",
        )

    def test_purdue_two_dated_fall_applications_are_ambiguous(self):
        html = purdue(
            "<p>Fall 2027</p><p>January 15, 2027</p>"
            "<p>Fall 2027</p><p>January 20, 2027</p>"
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=PURDUE)[0],
            "ambiguous_deadline",
        )

    def test_purdue_schoolwide_date_does_not_verify_unrelated_site(self):
        html = purdue("<p>Fall 2027</p><p>January 15, 2027</p>")
        self.assertNotEqual(
            collect_official_deadline(
                html, now=NOW,
                source_url="https://business.other-university.edu/phd/admissions.php",
            )[0],
            "verified",
        )

    def test_wharton_applied_economics_inherits_doctoral_application_cutoff(self):
        html = wharton(
            "The application for Fall 2027 is now open. The deadline "
            "to apply is December 15, 2026, 11:59PM EST."
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=WHARTON)[:2],
            ("verified", "2026-12-15"),
        )

    def test_wharton_no_applied_economics_scope_cannot_promote(self):
        html = wharton(
            "The deadline to apply is December 15, 2026.",
            applied_econ=False,
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=WHARTON)[0],
            "verified",
        )

    def test_wharton_mba_admissions_cutoff_is_not_doctoral(self):
        html = wharton(
            "The deadline to apply is December 15, 2026.",
            doctoral=False,
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=WHARTON)[0],
            "verified",
        )

    def test_wharton_application_deadline_is_not_only_a_gre_date(self):
        html = wharton(
            "All tests must be taken by December 15, 2026."
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=WHARTON)[0],
            "verified",
        )

    def test_wharton_yearless_application_date_is_not_confirmed(self):
        html = wharton(
            "The deadline to apply is December 15."
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=WHARTON)[0],
            "verified",
        )

    def test_wharton_multiple_explicit_application_cutoffs_are_ambiguous(self):
        html = wharton(
            "The deadline to apply for domestic applicants is "
            "December 15, 2026. For international applicants, "
            "the deadline to apply is January 5, 2027."
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=WHARTON)[0],
            "ambiguous_deadline",
        )


if __name__ == "__main__":
    unittest.main()
