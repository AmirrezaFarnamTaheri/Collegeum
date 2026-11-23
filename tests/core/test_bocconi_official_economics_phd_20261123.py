"""Bocconi Economics PhD official current-cycle multi-programme cutoff tests.

Realistic reduced primary-source language, not a hard-coded calendar date.
The alternate February cutoff belongs to other named PhD programmes.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from datetime import UTC, datetime

from tools.update_phd_admissions import (
    collect_official_deadline,
    investigate_official_pages,
)

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)
BOCCONI = (
    "https://www.unibocconi.it/en/programs/phd/"
    "admission-phd-programs/preparing-apply"
)
HEADER = (
    "<h1>Preparing to Apply</h1>"
    "<p>Bocconi University hereby announces the Public Call for Applications "
    "to the 43rd cycle (academic year 2027/2028) of the following PhD programs:</p>"
    "<ul><li>Business Administration and Management (BA&M)</li>"
    "<li>Economics and Finance (EC-FIN)</li>"
    "<li>Legal Studies (LS)</li>"
    "<li>Statistics and Machine Learning (STAT-ML)</li>"
    "<li>Computing Sciences and Artificial Intelligence (CS-AI)</li></ul>"
)
EXCEPTION = (
    " (8 February 2027 at 23:59 CET for Statistics and Machine Learning "
    "and Computing Sciences and Artificial Intelligence)"
)
CLOSING = (
    "The deadline for submitting the application is 18 January 2027 "
    "at 23:59 CET"
)


class BocconiOfficialAdmissionsTests(unittest.TestCase):
    def test_economics_and_finance_uses_ordinary_cutoff_not_other_programmes(self):
        html = (
            HEADER + "<h2>Application Procedure</h2><p>"
            + CLOSING + EXCEPTION + ". This deadline is not negotiable.</p>"
        )
        status, day, excerpt = collect_official_deadline(
            html, now=NOW, source_url=BOCCONI,
        )
        self.assertEqual((status, day), ("verified", "2027-01-18"))
        self.assertIn("deadline for submitting the application", excerpt.lower())
        self.assertIn("18 January 2027", excerpt)
        self.assertNotIn("8 February 2027", excerpt)

    def test_same_host_evidence_is_provenanced_through_investigation(self):
        html = HEADER + "<h2>Application Procedure</h2><p>" + CLOSING + EXCEPTION + "</p>"
        observed = investigate_official_pages(
            BOCCONI, now=NOW,
            fetch_html=lambda url: (html, url),
            robots_allowed=lambda url: True,
            max_pages=1,
        )
        self.assertEqual(observed["status"], "verified")
        self.assertEqual(observed["deadline_iso"], "2027-01-18")
        self.assertEqual(observed["evidence_url"], BOCCONI)
        self.assertEqual(observed["investigated_urls"], [BOCCONI])

    def test_not_an_economics_phd_if_programme_is_absent(self):
        html = HEADER.replace("<li>Economics and Finance (EC-FIN)</li>", "")
        html += "<p>" + CLOSING + EXCEPTION + "</p>"
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=BOCCONI)[0],
            "verified",
        )

    def test_economics_in_exception_list_must_not_receive_general_cutoff(self):
        html = HEADER + "<p>" + CLOSING + (
            " (8 February 2027 for Economics and Finance)"
        ) + "</p>"
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=BOCCONI)[0],
            "verified",
        )

    def test_not_verified_on_imitation_different_host(self):
        html = HEADER + "<p>" + CLOSING + EXCEPTION + "</p>"
        self.assertNotEqual(
            collect_official_deadline(
                html, now=NOW,
                source_url="https://admissions.example.org/bocconi/preparing-apply",
            )[0], "verified",
        )

    def test_outdated_cycle_not_recycled_for_new_intake(self):
        html = HEADER.replace("2027/2028", "2025/2026")
        html += "<p>The deadline for submitting the application is 18 January 2026.</p>"
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=BOCCONI)[0],
            "verified",
        )

    def test_discovery_lead_points_to_the_same_official_programme_call(self):
        root = Path(__file__).resolve().parents[2]
        seeds = json.loads(
            (root / "config/phd_admissions_seeds.json").read_text(encoding="utf-8")
        )
        public = json.loads(
            (root / "docs/data/phd_admissions.json").read_text(encoding="utf-8")
        )
        for catalog in (seeds, public):
            programme = next(
                row for row in catalog["programmes"]
                if row["institution"] == "Bocconi University"
            )
            self.assertEqual(programme["official_programme_url"], BOCCONI)

    def test_disagreeing_economics_specific_cutoffs_are_ambiguous(self):
        html = (
            HEADER + "<p>" + CLOSING + EXCEPTION + "</p>"
            "<p>Economics and Finance PhD application deadline: 20 January 2027.</p>"
        )
        status, day, excerpt = collect_official_deadline(
            html, now=NOW, source_url=BOCCONI,
        )
        self.assertEqual(status, "ambiguous_deadline")
        self.assertIsNone(day)
        self.assertIsNone(excerpt)


if __name__ == "__main__":
    unittest.main()
