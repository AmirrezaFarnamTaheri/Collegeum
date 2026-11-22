"""Official Economics PhD deadlines on department-specific pages require provenance."""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.update_phd_admissions import collect_official_deadline

NOW = datetime(2026, 11, 23, tzinfo=UTC)
TORONTO = "https://www.economics.utoronto.ca/index.php/index/graduate/phd"
ROCHESTER = "https://www.sas.rochester.edu/eco/graduate/apply.html"


class DepartmentContextTests(unittest.TestCase):
    def test_www_economics_department_phd_page_accepts_explicit_final_date(self):
        html = """
        <h1>Graduate Programs</h1>
        <h3>PhD program admission requirements</h3>
        <p>We offer both regular-entry and direct-entry PhD programs.
        Applicants must have completed a master's degree in economics or
        a related field. Students should carefully prepare all academic
        documents, review the faculty requirements, and select the
        programme corresponding to their academic qualifications.
        The regular-entry and direct-entry options have distinct
        prerequisites and need individual programme selection.</p>
        <h4>Deadlines</h4>
        <p>Once the online application and fee are paid
        (final deadline January 15, 2027), applicants receive a form.</p>
        """
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=TORONTO)[:2],
            ("verified", "2027-01-15"),
        )

    def test_rochester_departmental_graduate_application_scope(self):
        html = """
        <h1>Graduate Program</h1>
        <nav><a href="/eco/graduate/phd.html">PhD Program</a></nav>
        <p>Graduate student resources include placement, international
        opportunities, training and research facilities.
        Applicants can review the department's doctoral programme
        information and request more details about academic preparation.
        The process starts by selecting your area of research.
        Resources for interested students describe student life and
        faculty research interests in multiple economics fields.</p>
        <h2>Apply to Rochester</h2>
        <h3>How and When to Apply</h3>
        <p>Applicants can apply using our online application.
        The application deadline is December 15, 2026, and there
        is a $70 application fee.</p>
        <footer>Department of Economics</footer>
        """
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=ROCHESTER)[:2],
            ("verified", "2026-12-15"),
        )

    def test_rochester_undergraduate_page_is_not_doctoral_evidence(self):
        html = """
        <h1>Undergraduate Admissions</h1>
        <nav><a href="/eco/graduate/phd.html">PhD Program</a></nav>
        <p>Department of Economics</p>
        <p>The application deadline is December 15, 2026.</p>
        """
        self.assertNotEqual(
            collect_official_deadline(
                html, now=NOW,
                source_url="https://www.sas.rochester.edu/eco/undergraduate/apply.html",
            )[0], "verified",
        )

    def test_rochester_masters_application_is_not_promoted_to_phd(self):
        html = """
        <h1>Graduate Program</h1>
        <nav><a href="/eco/graduate/phd.html">PhD Program</a></nav>
        <p>Department of Economics</p>
        <h2>Master of Arts admissions</h2>
        <p>The Master's application deadline is December 15, 2026.</p>
        """
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=ROCHESTER)[0],
            "verified",
        )

    def test_funding_priority_does_not_make_final_phd_cutoff_ambiguous(self):
        html = """
        <h1>Economics PhD</h1>
        <h2>PhD Application Deadlines</h2>
        <ul>
          <li>Priority Financial Support: December 2, 2026</li>
          <li>Final Deadline: December 16, 2026</li>
        </ul>
        """
        self.assertEqual(
            collect_official_deadline(
                html, now=NOW,
                source_url="https://econ.ucsb.edu/programs/graduate/apply",
            )[:2],
            ("verified", "2026-12-16"),
        )

    def test_funding_priority_alone_is_not_confirmed_application_deadline(self):
        html = """
        <h1>Economics PhD</h1>
        <h2>PhD Application Deadlines</h2>
        <li>Priority Financial Support: December 2, 2026</li>
        <li>Final Deadline: December 16 (year not yet announced)</li>
        """
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW)[0], "verified",
        )

    def test_economics_phd_university_directory_card_with_dated_deadline(self):
        html = """
        <h1>Economics</h1>
        <h2>Application Deadline</h2>
        <p>Degrees Offered</p>
        <p>Doctor of Philosophy (PhD)</p>
        <p>Deadline</p>
        <p>Dec 01, 2026 | 05:00 pm</p>
        """
        self.assertEqual(
            collect_official_deadline(
                html, now=NOW,
                source_url="https://gsas.harvard.edu/program/economics",
            )[:2],
            ("verified", "2026-12-01"),
        )

    def test_economics_masters_only_directory_card_stays_unverified(self):
        html = """
        <h1>Economics</h1>
        <h2>Application Deadline</h2>
        <p>Degrees Offered</p>
        <p>Master of Arts</p>
        <p>Deadline</p>
        <p>Dec 01, 2026 | 05:00 pm</p>
        """
        self.assertNotEqual(
            collect_official_deadline(
                html, now=NOW,
                source_url="https://gsas.example.edu/program/economics",
            )[0], "verified",
        )

    def test_generic_graduate_site_with_phd_navigation_is_not_enough(self):
        html = """
        <h1>Graduate Program</h1>
        <nav><a href="/eco/graduate/phd.html">PhD Program</a></nav>
        <p>Department of Economics</p>
        <h2>How and When to Apply</h2>
        <p>The application deadline is December 15, 2026.</p>
        """
        self.assertNotEqual(
            collect_official_deadline(
                html, now=NOW,
                source_url="https://www.university.example.edu/graduate/apply.html",
            )[0], "verified",
        )


if __name__ == "__main__":
    unittest.main()
