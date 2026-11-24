"""UBC Vancouver School of Economics PhD intake / role-aware deadlines.

Do not infer programme deadlines from the department FAQ, another graduate
programme, a future intake that is not yet open, or the transcript/referee
deadlines. Only the University's official PhD-Economics entry is evidence.
"""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tools.update_phd_admissions import collect_official_deadline, validate_catalogues

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 24, 10, tzinfo=UTC)
OFFICIAL = "https://www.grad.ubc.ca/prospective-students/graduate-degree-programs/phd-economics"
FAQ = "https://economics.ubc.ca/graduate/prospective-students/phd-program/faq/"


def ubc_page(
    *, degree: str = "Doctor of Philosophy in Economics (PhD)",
    canadian: str = "21 December 2026",
    international: str = "21 December 2026",
    future: bool = True,
    current: bool = True,
) -> str:
    first = (
        "<h4>September 2027 Intake</h4>"
        "<p>Application Open Date 15 October 2026</p>"
        "<h5>Canadian Applicants</h5>"
        f"<p>Application Deadline {canadian}</p>"
        "<p>Transcript Deadline 3 January 2027</p>"
        "<p>Referee Deadline 3 January 2027</p>"
        "<h5>International Applicants</h5>"
        f"<p>Application Deadline {international}</p>"
        "<p>Transcript Deadline 3 January 2027</p>"
        "<p>Referee Deadline 3 January 2027</p>"
        if current else ""
    )
    second = (
        "<h4>September 2028 Intake</h4>"
        "<p>Application Open Date 15 October 2027</p>"
        "<h5>Canadian Applicants</h5>"
        "<p>Application Deadline 21 December 2027</p>"
        "<p>Transcript Deadline 3 January 2028</p>"
        "<p>Referee Deadline 3 January 2028</p>"
        "<h5>International Applicants</h5>"
        "<p>Application Deadline 21 December 2027</p>"
        "<p>Transcript Deadline 3 January 2028</p>"
        "<p>Referee Deadline 3 January 2028</p>"
        if future else ""
    )
    return (
        f"<h1>{degree}</h1>"
        "<p>The Ph.D. program in economics at UBC</p>"
        "<p>Vancouver School of Economics</p>"
        "<h2>Admission Information &amp; Requirements</h2>"
        "<h2>2) Meet Deadlines</h2>"
        + first + second
        + "<h5>Deadline Explanations</h5>"
        "<p>Application Deadline: Deadline to submit online application.</p>"
    )


class UBCEconomicsCurrentIntakeTests(unittest.TestCase):
    def test_catalogue_uses_official_grad_degree_listing_instead_of_department_faq(self):
        seeds = json.loads(
            (ROOT / "config/phd_admissions_seeds.json").read_text(encoding="utf-8")
        )
        public = json.loads(
            (ROOT / "docs/data/phd_admissions.json").read_text(encoding="utf-8")
        )
        validate_catalogues(seeds, public)
        seed = next(x for x in seeds["programmes"]
                    if x["institution"] == "University of British Columbia")
        entry = next(x for x in public["programmes"]
                     if x["institution"] == "University of British Columbia")
        self.assertEqual(seed["official_programme_url"], OFFICIAL)
        self.assertEqual(entry["official_programme_url"], OFFICIAL)
        if entry["status"] == "verified":
            self.assertEqual(entry["deadline_iso"], "2026-12-21")
            self.assertTrue(entry["evidence_url"].startswith(OFFICIAL))
        else:
            self.assertIsNone(entry["deadline_iso"])
            self.assertIsNone(entry["evidence_url"])

    def test_open_2027_cycle_has_same_full_year_deadline_for_both_applicant_groups(self):
        status, cutoff, excerpt = collect_official_deadline(
            ubc_page(), now=NOW, source_url=OFFICIAL,
        )
        self.assertEqual((status, cutoff), ("verified", "2026-12-21"))
        self.assertIn("21 December 2026", excerpt)

    def test_referee_deadline_and_transcript_deadline_are_not_application_deadlines(self):
        self.assertEqual(
            collect_official_deadline(ubc_page(), now=NOW, source_url=OFFICIAL)[:2],
            ("verified", "2026-12-21"),
        )

    def test_different_canadian_and_international_cutoffs_are_ambiguous(self):
        self.assertEqual(
            collect_official_deadline(
                ubc_page(international="22 December 2026"),
                now=NOW, source_url=OFFICIAL,
            )[0],
            "ambiguous_deadline",
        )

    def test_yearless_date_and_inactive_future_cycle_do_not_verify(self):
        for html in (
            ubc_page(canadian="21 December", international="21 December"),
            ubc_page(current=False),
        ):
            with self.subTest(html=html):
                self.assertNotEqual(
                    collect_official_deadline(html, now=NOW, source_url=OFFICIAL)[0],
                    "verified",
                )

    def test_after_2028_intake_opens_it_is_the_current_cycle(self):
        status, cutoff, _ = collect_official_deadline(
            ubc_page(), now=datetime(2027, 11, 24, tzinfo=UTC),
            source_url=OFFICIAL,
        )
        self.assertEqual((status, cutoff), ("verified", "2027-12-21"))

    def test_masters_other_host_and_department_faq_cannot_supply_phd_date(self):
        for html, url in (
            (ubc_page(degree="Master of Arts in Economics"), OFFICIAL),
            (ubc_page(), FAQ),
            (ubc_page(), "https://other.example.edu/prospective-students/graduate-degree-programs/phd-economics"),
        ):
            with self.subTest(url=url, html=html):
                self.assertNotEqual(
                    collect_official_deadline(html, now=NOW, source_url=url)[0],
                    "verified",
                )


if __name__ == "__main__":
    unittest.main()
