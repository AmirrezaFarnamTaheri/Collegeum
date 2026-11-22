"""Official current-cycle HTML regressions and one-pass review coverage.

The official text fragments below are reduced examples of public 2026-27
university admissions instructions, not third-party deadline imports.
"""
from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

from predoc_pipeline.core.official_call_evidence import explicit_official_deadline
from tools.update_phd_admissions import (
    collect_official_deadline,
    refresh_inconclusive,
)

NOW = datetime(2026, 11, 22, 18, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


class MoreOfficialPhDDeadlineEvidenceTests(unittest.TestCase):
    def test_mit_economics_doctoral_track_text_and_dated_closing(self):
        html = (
            "<h1>Admissions</h1>"
            "<p>You can apply to our doctoral program (both the economics "
            "and business economics tracks) from September 15 to December 15 "
            "for admission the following September.</p>"
            "<p>The application for a September 2027 start is now available "
            "through December 15, 2026.</p>"
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW)[:2],
            ("verified", "2026-12-15"),
        )

    def test_emery_economics_department_application_table(self):
        html = (
            "<h1>Apply to the PhD Program</h1>"
            "<p>Applications for Fall 2027 admission are open.</p>"
            "<table><tr><td>Sep 2026 to Jan 1, 2027</td>"
            "<td>Jan 1, 2027</td><td>Jan/Feb/Mar/early April</td></tr>"
            "<tr><td>Application submission period.</td>"
            "<td>Deadline for submission of your application.</td>"
            "<td>Department timeline for decisions.</td></tr></table>"
        )
        self.assertEqual(
            collect_official_deadline(
                html, now=NOW,
                source_url="https://economics.emory.edu/doctoral/apply-to-phd/index.html",
            )[:2], ("verified", "2027-01-01"),
        )

    def test_general_university_phd_table_not_attributed_to_economics(self):
        html = (
            "<h1>Apply to the PhD Program</h1>"
            "<table><tr><td>Jan 1, 2027</td></tr>"
            "<tr><td>Deadline for submission of your application</td></tr></table>"
        )
        self.assertNotEqual(
            collect_official_deadline(
                html, now=NOW,
                source_url="https://gradschool.example.edu/doctoral/index.html",
            )[0], "verified",
        )

    def test_deadline_role_from_different_table_cannot_verify_date(self):
        html = (
            "<h1>Economics PhD admissions</h1>"
            "<table><tr><td>Jan 1, 2027</td><td>Apr 3, 2027</td>"
            "</tr></table>"
            "<table><tr><td>Deadline for submission of your application"
            "</td><td>Unrelated instructions</td></tr></table>"
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW)[0], "verified",
        )

    def test_yale_phd_list_requires_economics_in_same_dated_group(self):
        html = (
            "<h1>Dates and Deadlines for PhD or Master's applicants</h1>"
            "<h2>December 1, 2026</h2>"
            "<p>Application deadline for:</p><ul>"
            "<li>Ecology</li><li>Economics</li><li>Psychology</li></ul>"
            "<h2>December 15, 2026</h2>"
            "<p>Application deadline for:</p><ul>"
            "<li>Physics</li><li>Finance</li></ul>"
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW)[:2],
            ("verified", "2026-12-01"),
        )

    def test_yale_group_does_not_borrow_economics_from_other_deadline(self):
        html = (
            "<h1>Dates and Deadlines for PhD applicants</h1>"
            "<h2>December 1, 2026</h2>"
            "<p>Application deadline for:</p><li>Biology</li>"
            "<h2>December 15, 2026</h2>"
            "<p>Application deadline for:</p><li>Economics</li>"
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW)[:2],
            ("verified", "2026-12-15"),
        )

    def test_masters_only_grouped_list_not_treated_as_economics_phd(self):
        html = (
            "<h1>Master's application deadlines</h1>"
            "<h2>December 1, 2026</h2>"
            "<p>Application deadline for:</p><li>Economics</li>"
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW)[0], "verified",
        )

    def test_bse_first_year_of_economics_phd_track_with_explicit_date(self):
        html = (
            "<h1>PhD Track Program</h1>"
            "<p>This program is the first year of the PhD in Economics "
            "and Finance at a university.</p>"
            "<p>2027-2028 applications are open!</p>"
            "<p>Application deadline: January 15, 2027</p>"
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW)[:2],
            ("verified", "2027-01-15"),
        )

    def test_numeric_european_nonambiguous_deadline_is_accepted(self):
        html = (
            "<h1>Doctoral programme in Economics</h1>"
            "<p>Application deadline: 15.12.2026.</p>"
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW)[:2],
            ("verified", "2026-12-15"),
        )

    def test_shared_publisher_gate_accepts_only_unambiguous_numeric_dates(self):
        self.assertTrue(explicit_official_deadline(
            "Application deadline: 15.12.2026",
            date(2026, 12, 15),
        ))
        self.assertFalse(explicit_official_deadline(
            "Application deadline: 03/04/2027",
            date(2027, 4, 3),
        ))

    def test_ambiguous_numeric_month_day_remains_unverified(self):
        html = (
            "<h1>Doctoral programme in Economics</h1>"
            "<p>Application deadline: 03/04/2027.</p>"
        )
        self.assertNotEqual(collect_official_deadline(html, now=NOW)[0], "verified")

    def test_full_review_is_opt_in_and_preserves_regular_cadence(self):
        workflow = (
            ROOT / ".github/workflows/phd-admissions-refresh.yml"
        ).read_text(encoding="utf-8")
        script = (
            ROOT / "tools/update_phd_admissions.py"
        ).read_text(encoding="utf-8")
        self.assertIn("full_recheck:", workflow)
        self.assertIn("--recheck-all-readable", workflow)
        self.assertIn("--recheck-no-explicit", workflow)
        self.assertIn("EVENT_NAME", workflow)
        self.assertIn("FULL_RECHECK", workflow)
        self.assertIn("timeout-minutes:", workflow)
        self.assertIn("recheck-all-readable", script)
        self.assertNotIn("TELEGRAM_BOT_TOKEN", workflow)

    def test_long_review_rebases_before_non_force_push(self):
        workflow = (
            ROOT / ".github/workflows/phd-admissions-refresh.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("git fetch origin main", workflow)
        self.assertIn("git rebase origin/main", workflow)
        self.assertNotIn("git push --force", workflow)

    def test_full_review_checks_each_inconclusive_exactly_once(self):
        seeds = json.loads(
            (ROOT / "config/phd_admissions_seeds.json").read_text(encoding="utf-8")
        )
        public = json.loads(
            (ROOT / "docs/data/phd_admissions.json").read_text(encoding="utf-8")
        )
        original = {
            row["official_programme_url"]
            for row in public["programmes"]
            if row["status"] == "no_explicit_deadline"
        }
        other = {
            row["official_programme_url"]
            for row in public["programmes"]
            if row["status"] != "no_explicit_deadline"
        }
        seen = []

        def fetch(url, *, now):
            seen.append(url)
            return {"status": "no_explicit_deadline"}

        result = refresh_inconclusive(
            seeds, public, now=NOW, batch_size=40, fetcher=fetch,
        )
        self.assertEqual(len(seen), len(original))
        self.assertEqual(set(seen), original)
        self.assertFalse(set(seen) & other)
        self.assertEqual(len(result["programmes"]), 251)
        self.assertTrue(all(
            row["deadline_iso"] is None
            for row in result["programmes"]
            if row["official_programme_url"] in original
        ))


if __name__ == "__main__":
    unittest.main()
