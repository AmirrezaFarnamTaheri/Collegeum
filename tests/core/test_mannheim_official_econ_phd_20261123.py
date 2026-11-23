"""Mannheim Economics doctoral admissions: final deadline, not early-review date."""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tools.update_phd_admissions import (
    collect_official_deadline,
    investigate_official_pages,
)

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)
OFFICIAL = "https://www.uni-mannheim.de/gess/apply/"
OFFICIAL_TEXT = (
    "<h1>How to Apply</h1>"
    "<p>Applications for the Fall 2027 intake are now open. "
    "Admission requirements for each center can be found here:</p>"
    "<ul><li>Admission Center for Doctoral Studies in Business</li>"
    "<li>Admission Center for Doctoral Studies in Economics</li>"
    "<li>Admission Center for Doctoral Studies in Social Science</li></ul>"
    "<h2>Online application portal</h2>"
    "<p>Final application deadline: 31 March 2027</p>"
    "<h2>Early applications</h2>"
    "<p>Applications handed in before 15 January 2027 will be treated "
    "as early applications and reviewed before the final deadline. "
    "Applications not accepted in the early round will be reviewed again "
    "after the final deadline of 31 March 2027.</p>"
)


class MannheimEconomicsPhDTests(unittest.TestCase):
    def test_final_cutoff_ignores_earlier_priority_review(self):
        status, day, evidence = collect_official_deadline(
            OFFICIAL_TEXT, now=NOW, source_url=OFFICIAL,
        )
        self.assertEqual((status, day), ("verified", "2027-03-31"))
        self.assertIn("Final application deadline: 31 March 2027", evidence)
        self.assertNotIn("15 January 2027", evidence)

    def test_official_provenance_is_recorded(self):
        row = investigate_official_pages(
            OFFICIAL, now=NOW,
            fetch_html=lambda url: (OFFICIAL_TEXT, url),
            robots_allowed=lambda url: True,
            max_pages=1,
        )
        self.assertEqual(row["deadline_iso"], "2027-03-31")
        self.assertEqual(row["evidence_url"], OFFICIAL)
        self.assertEqual(row["investigated_urls"], [OFFICIAL])

    def test_generic_phd_apply_page_is_not_economics(self):
        html = OFFICIAL_TEXT.replace(
            "<li>Admission Center for Doctoral Studies in Economics</li>", "",
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=OFFICIAL)[0],
            "verified",
        )

    def test_copied_page_off_host_is_not_credible(self):
        self.assertNotEqual(
            collect_official_deadline(
                OFFICIAL_TEXT, now=NOW,
                source_url="https://application.example.com/mannheim",
            )[0], "verified",
        )

    def test_explicit_economics_specific_conflict_is_ambiguous(self):
        html = OFFICIAL_TEXT + (
            "<p>Economics PhD application deadline: 2 April 2027.</p>"
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=OFFICIAL)[0],
            "ambiguous_deadline",
        )

    def test_official_source_is_used_as_discovery_lead(self):
        root = Path(__file__).resolve().parents[2]
        for relative in ("config/phd_admissions_seeds.json",
                         "docs/data/phd_admissions.json"):
            catalog = json.loads((root / relative).read_text(encoding="utf-8"))
            programme = next(
                p for p in catalog["programmes"]
                if p["institution"] == "University of Mannheim"
            )
            self.assertEqual(programme["official_programme_url"], OFFICIAL)


if __name__ == "__main__":
    unittest.main()
