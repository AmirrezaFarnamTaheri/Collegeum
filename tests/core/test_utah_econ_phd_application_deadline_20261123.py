"""Utah Economics PhD admissions: submission recommendation is not the cutoff.

The official department site announces Fall 2027 applications with an explicit
January 15, 2027 cutoff, but separately recommends December 31, 2026 for
processing time. Programme identity and current-year dates must be explicit.
"""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.update_phd_admissions import collect_official_deadline

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)
UTAH = "https://econ.utah.edu/phd-program/phd-admissions.php"


def utah_layout(
    *, degree: str = "PhD", cutoff: str = "January 15, 2027",
    recommend: str = "December 31, 2026", extra: str = "",
) -> str:
    return (
        "<header><a href='/'>Department of Economics</a></header>"
        "<h1>Program Admissions</h1>"
        f"<p>The requirements for admission to the {degree} program are:</p>"
        "<p>A master's degree in economics is not a requirement for admission.</p>"
        "<h2>Application Deadline</h2>"
        "<h4>Fall Admission: January 15</h4>"
        f"<p>We are now accepting applications for Fall 2027. We recommend "
        f"that applicants submit their applications by {recommend} to allow "
        "all materials to be processed by the application deadline of "
        f"{cutoff}.</p>"
        "<p>Applications for the PhD program are only accepted for Fall "
        "semester.</p>"
        "<h2>Application Procedure</h2>"
        "<p>Letters of recommendation must be submitted by the "
        "February 1st deadline to be considered.</p>"
        + extra
    )


class UtahCurrentCycleEconomicsPhdTests(unittest.TestCase):
    def test_dated_actual_application_cutoff_not_early_recommendation(self):
        status, deadline, excerpt = collect_official_deadline(
            utah_layout(), now=NOW, source_url=UTAH,
        )
        self.assertEqual((status, deadline), ("verified", "2027-01-15"))
        self.assertIn("January 15, 2027", excerpt)

    def test_yearless_deadline_must_not_borrow_year_from_fall_intake(self):
        status, date, excerpt = collect_official_deadline(
            utah_layout(cutoff="January 15"), now=NOW, source_url=UTAH,
        )
        self.assertNotEqual(status, "verified")
        self.assertIsNone(date)
        self.assertIsNone(excerpt)

    def test_recommendation_date_is_not_instead_the_application_cutoff(self):
        status, day, _ = collect_official_deadline(
            utah_layout(recommend="December 28, 2026"),
            now=NOW, source_url=UTAH,
        )
        self.assertEqual((status, day), ("verified", "2027-01-15"))

    def test_unrelated_master_or_university_page_cannot_inherit_cutoff(self):
        for html, url in (
            (utah_layout(degree="MA"), UTAH),
            (utah_layout(), "https://econ.utah.edu/masters-program/ma-admissions.php"),
            (utah_layout(), "https://not-utah.example.edu/phd-program/phd-admissions.php"),
        ):
            with self.subTest(url=url, html=html):
                self.assertNotEqual(
                    collect_official_deadline(html, now=NOW, source_url=url)[0],
                    "verified",
                )

    def test_expired_cutoff_is_never_promoted(self):
        status, day, _ = collect_official_deadline(
            utah_layout(cutoff="January 15, 2025"), now=NOW, source_url=UTAH,
        )
        self.assertNotEqual(status, "verified")
        self.assertIsNone(day)

    def test_conflicting_application_cutoffs_are_ambiguous(self):
        html = utah_layout(extra=(
            "<p>The application deadline is January 20, 2027.</p>"
        ))
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=UTAH)[0],
            "ambiguous_deadline",
        )


if __name__ == "__main__":
    unittest.main()
