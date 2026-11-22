"""Realistic current-cycle PhD admissions wording requires local programme proof."""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.update_phd_admissions import collect_official_deadline, refresh

NOW = datetime(2026, 11, 22, tzinfo=UTC)


class ProgrammeContextAdmissionsTests(unittest.TestCase):
    def test_mit_economics_doctoral_scope_precedes_explicit_application_date(self):
        html = """
        <h1>Admissions</h1>
        <p>You can apply to our doctoral program (both the economics
        and business economics tracks) from September 15-December 15
        for admission the following September.</p>
        <p>The application for a September 2027 start is now available
        at the MIT Application Management portal through December 15, 2026.</p>
        """
        self.assertEqual(
            collect_official_deadline(html, now=NOW)[:2],
            ("verified", "2026-12-15"),
        )

    def test_northwestern_department_and_phd_program_adjacent_to_deadline(self):
        html = """
        <h1>Admissions</h1>
        <p>The Department of Economics at Northwestern is committed to an
        individualized and holistic review of each application to the
        PhD program. This review will take into consideration the many
        challenges influencing applicants.</p>
        <p>The application will be available in September.
        The application deadline is December 15, 2026, 11:59pm CST.</p>
        """
        self.assertEqual(
            collect_official_deadline(html, now=NOW)[:2],
            ("verified", "2026-12-15"),
        )

    def test_mentoring_deadline_does_not_inherit_doctoral_programme_scope(self):
        html = """
        <h1>Admissions</h1>
        <p>You can apply to our doctoral program (both the economics
        and business economics tracks) in the autumn term.</p>
        <p>The student mentoring program's application deadline
        is December 12, 2026.</p>
        """
        self.assertNotEqual(collect_official_deadline(html, now=NOW)[0], "verified")

    def test_mba_deadline_does_not_inherit_economics_doctoral_scope(self):
        html = """
        <h1>Graduate admissions</h1>
        <p>The Department of Economics has a PhD program.
        We also have a number of other postgraduate programmes.</p>
        <p>For the MBA program, the application deadline
        is December 12, 2026.</p>
        """
        self.assertNotEqual(collect_official_deadline(html, now=NOW)[0], "verified")

    def test_parser_upgrades_recheck_all_readable_negatives_in_safe_batches(self):
        root = Path(__file__).resolve().parents[2]
        seeds = json.loads(
            (root / "config/phd_admissions_seeds.json").read_text(encoding="utf-8")
        )
        public = json.loads(
            (root / "docs/data/phd_admissions.json").read_text(encoding="utf-8")
        )
        stamped = "2026-11-22T10:00:00Z"
        for row in public["programmes"]:
            row.update(
                status="no_explicit_deadline", checked_at=stamped,
                deadline_iso=None, evidence_url=None, evidence_excerpt=None,
                official_details={}, investigated_urls=[],
            )
            row.pop("extractor_revision", None)
        # A robots-blocked page must not be retried early by code upgrades.
        blocked_url = public["programmes"][0]["official_programme_url"]
        public["programmes"][0]["status"] = "robots_disallowed"

        fetched = []

        def fetch(url, *, now):
            fetched.append(url)
            return {"status": "no_explicit_deadline"}

        for cycle in range(10):
            public = refresh(
                seeds, public,
                now=NOW + timedelta(hours=6 * cycle),
                batch_size=25, fetcher=fetch,
            )
        self.assertEqual(len(fetched), 250)
        self.assertEqual(len(set(fetched)), 250)
        self.assertNotIn(blocked_url, fetched)

    def test_generic_doctoral_program_without_economics_is_not_proof(self):
        html = """
        <h1>Graduate admissions</h1>
        <p>Apply to our doctoral program in history or English.</p>
        <p>The application deadline is December 12, 2026.</p>
        """
        self.assertNotEqual(collect_official_deadline(html, now=NOW)[0], "verified")


if __name__ == "__main__":
    unittest.main()
