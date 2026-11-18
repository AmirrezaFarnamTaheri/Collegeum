"""Safeguards for the independent, MIT-attributed Economics PhD admissions reference.

This catalogue is not a vacancy source: undated upstream deadline guidance must
never enter live listing, deadline-countdown, or Telegram publishing paths.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "docs/data/phd_admissions.json"


class EconomicsPhDAdmissionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    def test_upstream_251_programmes_are_preserved_and_unique(self):
        entries = self.catalog["programmes"]
        self.assertEqual(len(entries), 251)
        keys = [(row["institution"].casefold(), row["country_code"]) for row in entries]
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual([row["institution"] for row in entries],
                         sorted((row["institution"] for row in entries), key=str.casefold))
        for row in entries:
            with self.subTest(institution=row["institution"]):
                self.assertRegex(row["country_code"], r"^[A-Z]{2}$")
                self.assertTrue(row["institution"].strip())
                self.assertTrue(row["deadline_guidance"].strip())
                self.assertNotRegex(row["deadline_guidance"], r"<[^>]*>")
                self.assertTrue(row["programme_structure"] is None or
                                (isinstance(row["programme_structure"], str) and
                                 bool(row["programme_structure"].strip())))
                url = urlparse(row["programme_url"])
                self.assertIn(url.scheme, ("https", "http"))
                self.assertTrue(url.netloc)

    def test_provenance_and_uncertainty_are_explicit(self):
        source = self.catalog["source"]
        self.assertEqual(self.catalog["kind"], "economics_phd_admissions_reference")
        self.assertEqual(self.catalog["scope"], "reference_only")
        self.assertEqual(source["name"], "Economics PhD App Deadlines")
        self.assertEqual(source["repository_url"],
                         "https://github.com/paultran47/econ-grad-app-deadlines")
        self.assertRegex(source["upstream_commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(source["upstream_path"], "index.md")
        self.assertEqual(source["license"], "MIT")
        self.assertRegex(source["snapshot_date_utc"], r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$")
        self.assertIs(source["deadline_years_verified"], False)
        self.assertIs(source["current_cycle_verified"], False)
        for row in self.catalog["programmes"]:
            self.assertFalse(set(row) & {"deadline", "deadline_iso", "days_left",
                                         "funded", "active", "published", "application_open"})

    def test_native_dashboard_keeps_admissions_separate_from_vacancies(self):
        page = (ROOT / "docs/index.html").read_text(encoding="utf-8")
        self.assertIn('href="#phd-admissions"', page)
        self.assertIn('id="phd-admissions"', page)
        self.assertIn("data/phd_admissions.json", page)
        self.assertIn('id="phd-admissions-search"', page)
        self.assertIn('id="phd-admissions-country"', page)
        self.assertIn('id="phd-admissions-more"', page)
        self.assertIn("Admissions are not employment vacancies", page)
        self.assertIn("not verified for the current admission cycle", page)
        self.assertIn("paultran47/econ-grad-app-deadlines", page)
        self.assertIn("licenses/econ-grad-app-deadlines-MIT.txt", page)

    def test_pages_deployment_includes_catalogue_and_license(self):
        workflow = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        self.assertIn("phd_admissions.json", workflow)
        self.assertIn("econ-grad-app-deadlines-MIT.txt", workflow)

    def test_mit_notice_is_retained_in_project(self):
        notice = (ROOT / "docs/licenses/econ-grad-app-deadlines-MIT.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("Copyright (c) 2026 Paul L. Tran", notice)
        self.assertIn("The above copyright notice and this permission notice", notice)
        self.assertIn("THE SOFTWARE IS PROVIDED", notice)


if __name__ == "__main__":
    unittest.main()
