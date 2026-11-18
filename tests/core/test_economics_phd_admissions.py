"""Contract and offline regression tests for official Economics PhD admissions monitoring."""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from tools.update_phd_admissions import (
    collect_official_deadline, eligible_for_check, validate_catalogues,
)

ROOT = Path(__file__).resolve().parents[2]


class EconomicsPhDAdmissionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seeds = json.loads(
            (ROOT / "config/phd_admissions_seeds.json").read_text(encoding="utf-8")
        )
        cls.public = json.loads(
            (ROOT / "docs/data/phd_admissions.json").read_text(encoding="utf-8")
        )

    def test_all_251_official_programme_leads_preserved(self):
        self.assertEqual(len(self.seeds["programmes"]), 251)
        self.assertEqual(len(self.public["programmes"]), 251)
        validate_catalogues(self.seeds, self.public)
        keys = [(p["institution"].casefold(), p["country_code"])
                for p in self.seeds["programmes"]]
        self.assertEqual(len(keys), len(set(keys)))
        for entry in self.seeds["programmes"]:
            with self.subTest(programme=entry["institution"]):
                url = urlparse(entry["official_programme_url"])
                self.assertIn(url.scheme, ("https", "http"))
                self.assertTrue(url.netloc)
                self.assertNotIn("deadline", entry)
                self.assertNotIn("deadline_guidance", entry)

    def test_upstream_is_only_a_lead_not_deadline_authority(self):
        self.assertEqual(self.seeds["source"]["license"], "MIT")
        self.assertEqual(self.seeds["source"]["upstream_commit"],
                         "49604886769441a11c1e79ab7d1fab68ba5b3d36")
        self.assertEqual(self.public["kind"], "economics_phd_admissions_observations")
        self.assertEqual(self.public["scope"], "official_programme_sources_only")
        self.assertIs(self.public["source"]["deadline_values_reused"], False)
        for entry in self.public["programmes"]:
            self.assertNotIn("deadline_guidance", entry)
            self.assertNotIn("published", entry)
            if entry["status"] != "verified":
                self.assertIsNone(entry["deadline_iso"])
            if entry["status"] == "verified":
                self.assertTrue(entry["evidence_url"])
                self.assertTrue(entry["evidence_excerpt"])
                self.assertTrue(entry["checked_at"])

    def test_ambiguous_or_yearless_deadlines_are_never_verified(self):
        now = datetime(2026, 11, 19, tzinfo=UTC)
        samples = [
            "PhD in Economics Application deadline: 15 December.",
            "PhD in Economics: Rolling admissions.",
            "Economics PhD deadline: 1 December 2026; domestic deadline: 15 January 2027.",
            "Statistics PhD deadline: December 20, 2026. Economics is also offered here.",
            "Economics PhD deadline was December 1, 2025.",
        ]
        for html in samples:
            with self.subTest(html=html):
                status, date, excerpt = collect_official_deadline(html, now=now)
                self.assertNotEqual(status, "verified")
                self.assertIsNone(date)

    def test_explicit_current_year_deadline_has_source_context(self):
        now = datetime(2026, 11, 19, tzinfo=UTC)
        cases = [
            ("<h1>Economics PhD admission</h1>"
             "<p>Applications deadline: December 15, 2026.</p>", "2026-12-15"),
            ("<p>Economics doctoral applications deadline: 10 January 2027.</p>",
             "2027-01-10"),
        ]
        for html, expected in cases:
            with self.subTest(html=html):
                status, date, excerpt = collect_official_deadline(html, now=now)
                self.assertEqual(status, "verified")
                self.assertEqual(date, expected)
                self.assertIn("deadline", excerpt.lower())

    def test_stale_verified_evidence_is_not_current(self):
        now = datetime(2026, 11, 19, tzinfo=UTC)
        self.assertTrue(eligible_for_check(
            {"status": "verified", "checked_at": "2026-10-25T00:00:00Z"}, now=now
        ))
        self.assertFalse(eligible_for_check(
            {"status": "verified", "checked_at": "2026-11-18T00:00:00Z"}, now=now
        ))

    def test_dashboard_is_native_and_never_mixes_vacancy_feed(self):
        page = (ROOT / "docs/index.html").read_text(encoding="utf-8")
        for text in (
            'href="#phd-admissions"', 'id="phd-admissions"',
            'data/phd_admissions.json', 'id="phd-admissions-search"',
            'id="phd-admissions-country"', 'id="phd-admissions-more"',
            "Admissions are not employment vacancies",
            "not verified for the current admission cycle",
            "paultran47/econ-grad-app-deadlines",
        ):
            self.assertIn(text, page)
        self.assertIn("function renderAdmissions()", page)
        self.assertNotIn("listings = listings.concat(admissions", page)

    def test_daily_refresh_is_automatic_but_not_broadcasting(self):
        workflow = (ROOT / ".github/workflows/phd-admissions-refresh.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("schedule:", workflow)
        self.assertIn("tools/update_phd_admissions.py", workflow)
        self.assertIn("contents: write", workflow)
        self.assertNotIn("telegram", workflow.lower())
        pages = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        self.assertIn("phd-admissions-refresh", pages)
        self.assertIn("phd_admissions.json", pages)
        self.assertIn("econ-grad-app-deadlines-MIT.txt", pages)

    def test_mit_license_and_official_only_policy_documented(self):
        notice = (ROOT / "docs/licenses/econ-grad-app-deadlines-MIT.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("Copyright (c) 2026 Paul L. Tran", notice)
        self.assertIn("The above copyright notice and this permission notice", notice)
        self.assertIn("THE SOFTWARE IS PROVIDED", notice)
        docs = (ROOT / "docs/ECON_PHD_ADMISSIONS.md").read_text(encoding="utf-8")
        self.assertIn("official", docs.lower())
        self.assertIn("not", docs.lower())


if __name__ == "__main__":
    unittest.main()
