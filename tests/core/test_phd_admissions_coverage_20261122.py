"""Regressions for explicit official 2026-27 Economics PhD deadlines.

Fictionalised HTML fixtures model official institution wording; no upstream
application dates are used to assert production facts.
"""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.update_phd_admissions import collect_official_deadline, select_official_links

NOW = datetime(2026, 11, 22, 15, tzinfo=UTC)
SOURCE = "https://economics.example.edu/phd/admissions"


class PhDAdmissionsCoverageTests(unittest.TestCase):
    def test_us_doctoral_program_wording_and_no_later_than(self):
        html = (
            "<h1>Doctoral Program in Economics</h1>"
            "<p>Applications must be submitted online no later than "
            "January 6, 2027, 11:59 p.m.</p>"
        )
        self.assertEqual(collect_official_deadline(html, now=NOW)[:2],
                         ("verified", "2027-01-06"))

    def test_programme_after_deadline_label_is_explicit_context(self):
        html = (
            "<h1>Applying to Stanford</h1>"
            "<p>The application deadline for the Economics Ph.D. is "
            "December 2, 2026 (11:59pm).</p>"
        )
        self.assertEqual(collect_official_deadline(html, now=NOW)[:2],
                         ("verified", "2026-12-02"))

    def test_economics_phd_application_available_through_a_date(self):
        html = (
            "<h1>Economics PhD admissions</h1>"
            "<p>The application for a September 2027 start is now "
            "available at our official application portal "
            "through December 15, 2026.</p>"
        )
        self.assertEqual(collect_official_deadline(html, now=NOW)[:2],
                         ("verified", "2026-12-15"))

    def test_ordinal_and_abbreviated_month_forms(self):
        for html, iso in (
            (
                "<h1>Economics PhD</h1><p>Application deadline: "
                "15th December 2026.</p>", "2026-12-15",
            ),
            ("<h1>Economics PhD</h1><p>Application deadline: Dec. 15, 2026.</p>", "2026-12-15"),
        ):
            with self.subTest(html=html):
                self.assertEqual(collect_official_deadline(html, now=NOW)[:2],
                                 ("verified", iso))

    def test_economics_mres_phd_intake_closing_not_opening_date(self):
        html = (
            "<h1>Economics MRes/PhD</h1>"
            "<p>Applications for 2027 entry open on 1 November 2026 "
            "and close on 15 January 2027.</p>"
        )
        self.assertEqual(collect_official_deadline(html, now=NOW)[:2],
                         ("verified", "2027-01-15"))

    def test_generic_admissions_date_and_ancillary_deadlines_stay_unverified(self):
        for html in (
            "<h1>Graduate admissions</h1><p>Application deadline: Dec. 15, 2026.</p>",
            "<h1>Economics PhD</h1><p>The reference-letter deadline is Dec. 15, 2026.</p>",
            "<h1>Economics PhD</h1><p>Applications open through the portal on Dec. 15, 2026.</p>",
        ):
            with self.subTest(html=html):
                self.assertNotEqual(collect_official_deadline(html, now=NOW)[0],
                                    "verified")

    def test_multiple_applicant_deadlines_remain_ambiguous(self):
        html = (
            "<h1>Economics PhD</h1>"
            "<p>International application deadline: Dec. 15, 2026.</p>"
            "<p>Domestic application deadline: Jan. 10, 2027.</p>"
        )
        self.assertEqual(collect_official_deadline(html, now=NOW)[0],
                         "ambiguous_deadline")

    def test_specific_phd_link_outranks_generic_undergraduate_admissions(self):
        html = (
            "<h1>Economics PhD</h1>"
            '<a href="/undergraduate/direct-admission">Admission deadlines and fees</a>'
            '<a href="/undergraduate/admissions">Application requirements</a>'
            '<a href="/graduate/phd/economics/how-to-apply">How to apply</a>'
        )
        self.assertEqual(select_official_links(html, SOURCE, max_links=1),
                         ["https://economics.example.edu/graduate/phd/economics/how-to-apply"])


if __name__ == "__main__":
    unittest.main()
