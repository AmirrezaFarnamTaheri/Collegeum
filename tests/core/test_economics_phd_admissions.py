"""Contract and offline regression tests for official Economics PhD admissions monitoring."""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from tools.update_phd_admissions import (
    collect_official_deadline,
    eligible_for_check,
    refresh,
    validate_catalogues,
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

    def test_official_admissions_period_uses_closing_not_open_or_documents(self):
        now = datetime(2026, 11, 19, tzinfo=UTC)
        university_html = """
            <h1>Aalto Doctoral Programme in Business, Economics and Finance</h1>
            <h2>Application instructions 2027</h2>
            <p>Admission schedule 2027: Application period opens on
            8 December 2026 at 09:00 (UTC+2) and closes on
            5 January 2027 at 23:59 (UTC+2).</p>
            <p>After submitting your application by the deadline on
            5 January 2027, attach electronic application documents
            before the document deadline on 12 January 2027.</p>
            <p>Admission decisions are published 19 February 2027.</p>
        """
        status, deadline, evidence = collect_official_deadline(
            university_html, now=now
        )
        self.assertEqual(status, "verified")
        self.assertEqual(deadline, "2027-01-05")
        self.assertIn("5 January 2027", evidence)

    def test_official_applicant_categories_cannot_be_silently_collapsed(self):
        now = datetime(2026, 11, 19, tzinfo=UTC)
        university_html = """
            <h1>PhD in Economics admissions</h1>
            <p>International application deadline: 15 December 2026.</p>
            <p>Domestic application deadline: 10 January 2027.</p>
        """
        status, deadline, evidence = collect_official_deadline(
            university_html, now=now
        )
        self.assertEqual(status, "ambiguous_deadline")
        self.assertIsNone(deadline)
        self.assertIsNone(evidence)

    def test_official_document_only_date_is_not_application_deadline(self):
        now = datetime(2026, 11, 19, tzinfo=UTC)
        university_html = """
            <h1>Economics PhD admissions</h1>
            <p>The supporting document deadline is 12 January 2027.</p>
            <p>Application closing date: please refer to the portal.</p>
        """
        status, deadline, _ = collect_official_deadline(
            university_html, now=now
        )
        self.assertNotEqual(status, "verified")
        self.assertIsNone(deadline)

    def test_official_long_form_programme_deadline_is_not_dropped(self):
        """Institutional pages often put programme + intake between label and date."""
        now = datetime(2026, 11, 19, tzinfo=UTC)
        institutional_html = """
          <h1>Application</h1>
          <p>The application deadline to the Berlin School of Economics
          PhD Program for the autumn 2027 intake is January 15, 2027.</p>
          <p>An information session will take place on December 2, 2026.</p>
          <p>Interviews will take place on March 3, 2027.</p>
          <p>Recommendation letters must reach the school by January 19, 2027.</p>
        """
        status, deadline, evidence = collect_official_deadline(
            institutional_html, now=now
        )
        self.assertEqual(status, "verified")
        self.assertEqual(deadline, "2027-01-15")
        self.assertIn("January 15, 2027", evidence)

    def test_applicant_document_or_interview_date_is_not_mistaken_for_application(self):
        now = datetime(2026, 11, 19, tzinfo=UTC)
        institutional_html = """
          <h1>Application</h1>
          <p>The supporting-document deadline to Berlin School of Economics
          PhD Program for autumn 2027 intake is January 19, 2027.</p>
          <p>The interview date to Berlin School of Economics PhD Program
          is March 3, 2027.</p>
        """
        status, deadline, evidence = collect_official_deadline(
            institutional_html, now=now
        )
        self.assertNotEqual(status, "verified")
        self.assertIsNone(deadline)
        self.assertIsNone(evidence)

    def test_checks_multiple_times_daily_without_rechecking_fresh_sources(self):
        workflow = (ROOT / ".github/workflows/phd-admissions-refresh.yml").read_text(
            encoding="utf-8"
        )
        schedules = [line for line in workflow.splitlines() if line.strip().startswith(
            '- cron:'
        )]
        self.assertEqual(len(schedules), 4, schedules)
        self.assertTrue(all('17' in entry for entry in schedules))
        now = datetime(2026, 11, 19, tzinfo=UTC)

        def fetch(_url: str, *, now: datetime) -> dict:
            return {"status": "no_explicit_deadline"}

        first = refresh(self.seeds, self.public, now=now, batch_size=25, fetcher=fetch)
        later = refresh(self.seeds, first, now=now + timedelta(hours=6),
                        batch_size=25, fetcher=fetch)
        first_ids = {
            index for index, row in enumerate(first["programmes"])
            if row["checked_at"] == now.isoformat().replace("+00:00", "Z")
        }
        second_ids = {
            index for index, row in enumerate(later["programmes"])
            if row["checked_at"] == (now + timedelta(hours=6)).isoformat().replace(
                "+00:00", "Z"
            )
        }
        self.assertEqual(len(first_ids), 25)
        self.assertEqual(len(second_ids), 25)
        self.assertFalse(first_ids & second_ids)

    def test_stale_verified_evidence_is_not_current(self):
        now = datetime(2026, 11, 19, tzinfo=UTC)
        self.assertTrue(eligible_for_check(
            {"status": "verified", "checked_at": "2026-10-25T00:00:00Z"}, now=now
        ))
        self.assertFalse(eligible_for_check(
            {"status": "verified", "checked_at": "2026-11-18T00:00:00Z"}, now=now
        ))

    def test_missed_daily_workflows_do_not_skip_never_checked_programmes(self):
        now = datetime(2026, 11, 19, tzinfo=UTC)
        def fetch(_url: str, *, now: datetime) -> dict:
            return {"status": "no_explicit_deadline"}
        first = refresh(self.seeds, self.public, now=now, batch_size=25,
                        fetcher=fetch)
        baseline_checked = {
            i for i, item in enumerate(self.public["programmes"])
            if item["checked_at"] is not None
        }
        first_checked = {
            i for i, item in enumerate(first["programmes"])
            if i not in baseline_checked and item["checked_at"] is not None
        }
        self.assertEqual(len(first_checked), 25)
        # GitHub may drop schedules for days. Never revisit previously checked
        # sources ahead of the unvisited programme leads.
        later = refresh(self.seeds, first, now=now + timedelta(days=11),
                        batch_size=25, fetcher=fetch)
        newly_checked = {
            i for i, item in enumerate(later["programmes"])
            if i not in baseline_checked and i not in first_checked
            and item["checked_at"] is not None
        }
        self.assertEqual(len(newly_checked), 25)
        self.assertTrue(all(
            later["programmes"][i]["checked_at"] ==
            first["programmes"][i]["checked_at"]
            for i in first_checked
        ))

    def test_expired_observation_is_withdrawn_without_waiting_for_manual_approval(self):
        now = datetime(2027, 1, 5, tzinfo=UTC)
        old = json.loads(json.dumps(self.public))
        index = 0
        old["programmes"][index].update(
            status="verified", checked_at="2026-12-01T03:17:00Z",
            deadline_iso="2026-12-15",
            evidence_url=old["programmes"][index]["official_programme_url"],
            evidence_excerpt="Economics PhD applications deadline 15 December 2026",
            official_details={}, investigated_urls=[],
        )
        validate_catalogues(self.seeds, old)
        updated = refresh(self.seeds, old, now=now, batch_size=25,
                          fetcher=lambda url, now: {"status": "no_explicit_deadline"})
        changed = updated["programmes"][index]
        self.assertEqual(changed["status"], "stale")
        self.assertIsNone(changed["deadline_iso"])
        self.assertIsNone(changed["evidence_url"])

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
        self.assertNotIn("telegram-sync", workflow.lower())
        self.assertNotIn("predoc-pipeline", workflow.lower())
        pages = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
        self.assertIn("phd-admissions-refresh", pages)
        self.assertIn("phd_admissions.json", pages)
        self.assertIn("econ-grad-app-deadlines-MIT.txt", pages)

    def test_parser_change_rechecks_readable_negative_without_retrying_blocked(self):
        now = datetime(2026, 11, 19, tzinfo=UTC)
        sample = json.loads(json.dumps(self.public))
        for row in sample["programmes"]:
            row.update(
                status="unverified", checked_at=None,
                deadline_iso=None, evidence_url=None, evidence_excerpt=None,
                official_details={}, investigated_urls=[],
            )
        recent = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        readable = sample["programmes"][0]
        blocked = sample["programmes"][1]
        readable.update(status="no_explicit_deadline", checked_at=recent)
        blocked.update(status="robots_disallowed", checked_at=recent)
        seen = []

        def fetch(url: str, *, now: datetime) -> dict:
            seen.append(url)
            return {"status": "no_explicit_deadline"}

        refreshed = refresh(
            self.seeds, sample, now=now, batch_size=25, fetcher=fetch,
            recheck_no_explicit=True,
        )
        self.assertEqual(len(seen), 25)
        self.assertIn(readable["official_programme_url"], seen)
        self.assertNotIn(blocked["official_programme_url"], seen)
        self.assertEqual(
            refreshed["programmes"][0]["checked_at"],
            now.isoformat().replace("+00:00", "Z"),
        )
        self.assertEqual(refreshed["programmes"][1]["checked_at"], recent)

        workflow = (ROOT / ".github/workflows/phd-admissions-refresh.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("--recheck-no-explicit", workflow)
        self.assertIn("github.event_name", workflow)

    def test_source_facts_fail_validation_when_unattributed_or_external(self):
        corrupted = json.loads(json.dumps(self.public))
        row = corrupted["programmes"][0]
        row["investigated_urls"] = [row["official_programme_url"]]
        row["official_details"] = {
            "tuition": {
                "value": "No tuition fees",
                "evidence_url": "https://admissions-aggregator.example/fees",
                "evidence_excerpt": "No tuition fees",
                "checked_at": row["checked_at"],
            },
        }
        with self.assertRaises(ValueError):
            validate_catalogues(self.seeds, corrupted)

    def test_trusted_source_update_enriches_existing_verified_admissions(self):
        now = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
        verified = [
            row for row in self.public["programmes"]
            if row["status"] == "verified" and not row.get("official_details")
        ]
        self.assertGreaterEqual(len(verified), 2)
        urls = {row["official_programme_url"] for row in verified}
        checked = []

        def fetch(url: str, *, now: datetime) -> dict:
            checked.append(url)
            if url in urls:
                old = next(
                    row for row in verified
                    if row["official_programme_url"] == url
                )
                return {
                    "status": "verified",
                    "deadline_iso": old["deadline_iso"],
                    "evidence_url": old["evidence_url"],
                    "evidence_excerpt": old["evidence_excerpt"],
                    "official_details": {
                        "tuition": {
                            "value": "No tuition fees",
                            "evidence_url": old["evidence_url"],
                            "evidence_excerpt": "Official university: no tuition fees",
                            "checked_at": now.isoformat().replace("+00:00", "Z"),
                        },
                    },
                    "investigated_urls": [old["evidence_url"]],
                }
            return {"status": "no_explicit_deadline"}

        result = refresh(
            self.seeds, self.public, now=now, batch_size=25,
            fetcher=fetch, recheck_no_explicit=True,
        )
        self.assertTrue(urls.issubset(set(checked)))
        for row in result["programmes"]:
            if row["official_programme_url"] in urls:
                self.assertEqual(row["official_details"]["tuition"]["value"],
                                 "No tuition fees")

    def test_trusted_extractor_upgrade_rechecks_verified_with_existing_old_details(self):
        now = datetime(2026, 11, 19, 13, 0, tzinfo=UTC)
        original = json.loads(json.dumps(self.public))
        earlier = [
            row for row in original["programmes"]
            if row["status"] == "verified" and row.get("official_details")
        ]
        self.assertGreaterEqual(len(earlier), 2)
        expected = {row["official_programme_url"] for row in earlier}
        checked = []

        def fetch(url: str, *, now: datetime) -> dict:
            checked.append(url)
            if url in expected:
                old = next(row for row in earlier if row["official_programme_url"] == url)
                return {
                    "status": "verified", "deadline_iso": old["deadline_iso"],
                    "evidence_url": old["evidence_url"],
                    "evidence_excerpt": old["evidence_excerpt"],
                    "official_details": {},
                    "investigated_urls": [old["evidence_url"]],
                }
            return {"status": "no_explicit_deadline"}

        refreshed = refresh(
            self.seeds, original, now=now, batch_size=25,
            fetcher=fetch, recheck_no_explicit=True,
        )
        self.assertTrue(expected.issubset(set(checked)))
        for row in refreshed["programmes"]:
            if row["official_programme_url"] in expected:
                self.assertFalse(row["official_details"])
                self.assertEqual(row["status"], "verified")

    def test_initial_source_changes_bootstrap_without_refresh_commit_loop(self):
        workflow = (ROOT / ".github/workflows/phd-admissions-refresh.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("  push:", workflow)
        self.assertIn("branches: [main]", workflow)
        self.assertIn('"tools/update_phd_admissions.py"', workflow)
        self.assertIn('"config/phd_admissions_seeds.json"', workflow)
        self.assertNotIn('"docs/data/phd_admissions.json"', workflow)

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
