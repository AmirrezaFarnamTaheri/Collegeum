"""Official single-programme graduate division degree and application evidence.

University graduate directories often use an Economics-only H1, and print
the doctoral degree in a separate section ahead of the dated deadline.
Accept that only when programme identity, doctoral-only admission and
an explicit current-year application cutoff are all on one official page.
"""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.update_phd_admissions import collect_official_deadline

NOW = datetime(2026, 11, 23, tzinfo=UTC)
UCLA = "https://grad.ucla.edu/programs/social-sciences/economics-department/economics/"


class EconomicsDivisionPageTests(unittest.TestCase):
    def test_official_ucla_economics_phd_degree_with_explicit_apply_date(self):
        html = """
        <h1>Economics</h1>
        <h2>Graduate Program: Economics</h2>
        <h3>DEGREES</h3>
        <p>UCLA's Graduate Program in Economics offers the following degrees:</p>
        <p>Doctor of Philosophy (Ph.D.)</p>
        <p>Masters available on Doctoral track</p>
        <h3>Admissions Requirements for the Graduate Major in Economics</h3>
        <h3>APPLYING</h3>
        <p>After exploring options, follow the graduate application process.</p>
        <h3>Deadlines to apply</h3>
        <p>December 1, 2026</p>
        <h3>Program Name</h3><p>Economics</p>
        <h3>Leading to the degree of</h3>
        <p>M.A., Ph.D. Admits only Ph.D. applicants.</p>
        """
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=UCLA)[:2],
            ("verified", "2026-12-01"),
        )

    def test_sibling_ucla_sociology_page_cannot_be_economics(self):
        html = """
        <h1>Sociology</h1>
        <h2>Graduate Program: Sociology</h2>
        <h3>DEGREES</h3><p>Doctor of Philosophy (Ph.D.)</p>
        <p>Economics department graduate students attend seminars.</p>
        <h3>Deadlines to apply</h3><p>December 1, 2026</p>
        <p>M.A., Ph.D. Admits only Ph.D. applicants.</p>
        """
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=UCLA)[0],
            "verified",
        )

    def test_only_masters_not_inherited_as_economics_phd(self):
        html = """
        <h1>Economics</h1><h2>Graduate Program: Economics</h2>
        <h3>DEGREES</h3><p>Master of Arts (M.A.)</p>
        <h3>Deadlines to apply</h3><p>December 1, 2026</p>
        <p>Admits Master's applicants only.</p>
        """
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=UCLA)[0],
            "verified",
        )

    def test_yearless_and_other_program_dates_remain_unverified(self):
        for text in (
            "<h3>Deadlines to apply</h3><p>December 1</p>",
            "<h3>Application opens</h3><p>December 1, 2026</p>",
        ):
            with self.subTest(text=text):
                html = (
                    "<h1>Economics</h1><h2>Graduate Program: Economics</h2>"
                    "<p>Doctor of Philosophy (Ph.D.)</p>" + text
                    + "<p>Admits only Ph.D. applicants.</p>"
                )
                self.assertNotEqual(
                    collect_official_deadline(html, now=NOW, source_url=UCLA)[0],
                    "verified",
                )


if __name__ == "__main__":
    unittest.main()
