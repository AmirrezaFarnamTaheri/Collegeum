"""Programme-scoped university PhD admission dates and safely numeric ambiguity.

Fictionalized HTML reproduces the structure of university-owned pages.
Source URLs are used only as discovery context and not as asserted deadlines.
"""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.update_phd_admissions import collect_official_deadline

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)
BROWN = "https://graduateprograms.brown.edu/graduate-program/economics-phd"
CHICAGO = "https://economics.uchicago.edu/phd-program/apply"
COLUMBIA = "https://www.gsas.columbia.edu/content/economics-phd"


class DedicatedEconomicsDoctoralAdmissionsTests(unittest.TestCase):
    def test_brown_phd_program_directory_with_separate_date_heading(self):
        html = (
            "<h1>Economics</h1><p>Ph.D.</p>"
            "<p>The Ph.D. program in Economics trains students to conduct research.</p>"
            "<p>" + ("Graduate research training and teaching. " * 20) + "</p>"
            "<h2>Application Information</h2>"
            "<h3>Dates/Deadlines</h3>"
            "<h4>Application Deadline</h4><p>January 1, 2027</p>"
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=BROWN)[:2],
            ("verified", "2027-01-01"),
        )

    def test_brown_masters_directory_cannot_inherit_doctoral_date(self):
        html = (
            "<h1>Economics</h1><p>Master of Arts in Economics</p>"
            "<p>University offers an unrelated Ph.D. program in Economics.</p>"
            "<p>" + ("Graduate study and research. " * 20) + "</p>"
            "<h2>Application Information</h2><h4>Application Deadline</h4>"
            "<p>January 1, 2027</p>"
        )
        self.assertNotEqual(
            collect_official_deadline(
                html, now=NOW,
                source_url="https://graduateprograms.brown.edu/graduate-program/economics-ma",
            )[0], "verified",
        )

    def test_brown_does_not_infer_year_from_a_yearless_deadline(self):
        html = (
            "<h1>Economics</h1><p>Ph.D. program in Economics</p>"
            "<h4>Application Deadline</h4><p>January 1</p>"
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=BROWN)[0],
            "verified",
        )

    def test_chicago_phd_apply_page_with_generic_apply_heading(self):
        html = (
            "<h1>Apply</h1>"
            '<nav><a href="/phd-program">PhD Program</a>'
            '<a href="/phd-program/apply">Apply</a></nav>'
            "<p>" + ("Doctoral study resources and academic training. " * 15) + "</p>"
            "<h2>Timeline</h2>"
            "<p>For enrollment in Autumn 2027, the application deadline is "
            "December 1, 2026 at 11:59 p.m. US Central Time.</p>"
            "<footer>Kenneth C. Griffin Department of Economics</footer>"
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=CHICAGO)[:2],
            ("verified", "2026-12-01"),
        )

    def test_chicago_masters_apply_page_cannot_use_a_dated_cutoff(self):
        html = (
            "<h1>Apply</h1><nav><a href='/phd-program'>PhD Program</a></nav>"
            "<h2>Timeline</h2><p>For Autumn 2027 enrollment, "
            "the application deadline is December 1, 2026.</p>"
            "<footer>Kenneth C. Griffin Department of Economics</footer>"
        )
        self.assertNotEqual(
            collect_official_deadline(
                html, now=NOW,
                source_url="https://economics.uchicago.edu/masters-programs/apply",
            )[0], "verified",
        )

    def test_chicago_other_department_same_path_is_not_economics(self):
        html = (
            "<h1>Apply</h1><nav><a href='/phd-program'>PhD Program</a></nav>"
            "<h2>Timeline</h2><p>The application deadline is December 1, 2026.</p>"
            "<footer>Department of Sociology</footer>"
        )
        self.assertNotEqual(
            collect_official_deadline(
                html, now=NOW,
                source_url="https://sociology.uchicago.edu/phd-program/apply",
            )[0], "verified",
        )

    def test_columbia_dedicated_phd_directory_supports_spelled_month(self):
        html = (
            "<h1>Economics, PhD</h1><p>Program Category: PhD Programs</p>"
            "<p>The Department of Economics offers a graduate program "
            "leading to the PhD in Economics.</p>"
            "<p>" + ("Academic study and research. " * 20) + "</p>"
            "<h2>Special Admissions Requirements</h2>"
            "<p>Deadline for Fall Admission: December 3, 2026</p>"
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=COLUMBIA)[:2],
            ("verified", "2026-12-03"),
        )

    def test_columbia_ambiguous_numeric_still_unverified(self):
        html = (
            "<h1>Economics, PhD</h1><p>Program Category: PhD Programs</p>"
            "<h2>Special Admissions Requirements</h2>"
            "<p>Deadline for Fall Admission:</p><p>12/3/2026</p>"
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=COLUMBIA)[0],
            "verified",
        )

    def test_columbia_economics_masters_directory_cannot_inherit_phd_deadline(self):
        html = (
            "<h1>Economics, MA</h1><p>Program Category: Master's Programs</p>"
            "<p>Our graduates continue to PhD programs in Economics.</p>"
            "<p>" + ("Academic study and research. " * 20) + "</p>"
            "<h2>Application Requirements</h2>"
            "<p>Deadline for Fall Admission: December 3, 2026</p>"
        )
        self.assertNotEqual(
            collect_official_deadline(
                html, now=NOW,
                source_url="https://www.gsas.columbia.edu/content/economics-ma",
            )[0], "verified",
        )


if __name__ == "__main__":
    unittest.main()
