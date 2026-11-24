"""Official Economics PhD admission FAQs and graduate-major deadline panels.

These cases mirror university-owned programme pages but include only fictitious
test fixtures. They must not promote Master's or other programmes' deadlines.
"""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tools.update_phd_admissions import (
    collect_official_deadline,
    investigate_official_pages,
    refresh_inconclusive,
)

NOW = datetime(2026, 11, 23, tzinfo=UTC)
MARYLAND = "https://www.econ.umd.edu/graduate/applications-and-admissions-faq"
UCLA = "https://grad.ucla.edu/programs/social-sciences/economics-department/economics/"
UCLA_REQUIREMENTS = "https://grad.ucla.edu/requirements/?app=admission&major=0246"


def maryland_html(answer: str, *, exclusivity: bool = True) -> str:
    return (
        "<h1>Applications and Admissions FAQ</h1>"
        "<h4>What is the application deadline?</h4>"
        "<p>" + answer + "</p>"
        "<h4>Can you send me information on the Ph.D. program in Economics?</h4>"
        "<p>All information about our Ph.D. program is available online.</p>"
        "<h4>Do you offer a master's program in Economics?</h4>"
        "<p>" + (
            "Our department offers admission only to students interested "
            "in earning a Ph.D. in economics. We do not accept master's-only applicants."
            if exclusivity else
            "Our department offers a separate M.A. in economics."
        ) + "</p>"
    )


class OfficialPhDFaqAndProgrammeRequirementTests(unittest.TestCase):
    def test_exclusive_economics_phd_faq_explicit_full_year_deadline(self):
        html = maryland_html(
            "Our application deadline for Fall 2027 is December 1, 2026. "
            "All applications are received by this deadline."
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=MARYLAND)[:2],
            ("verified", "2026-12-01"),
        )

    def test_nonexclusive_economics_faq_cannot_inherit_phd_cutoff(self):
        html = maryland_html(
            "Our M.A. application deadline is December 1, 2026.",
            exclusivity=False,
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=MARYLAND)[0],
            "verified",
        )

    def test_economics_phd_faq_ambiguous_application_dates_fail_closed(self):
        html = maryland_html(
            "Our application deadline for domestic students is December 1, 2026 "
            "and for international students is December 10, 2026."
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=MARYLAND)[0],
            "ambiguous_deadline",
        )

    def test_other_department_faq_cannot_use_economics_phd_admission_fact(self):
        html = maryland_html(
            "Our application deadline is December 1, 2026."
        )
        self.assertNotEqual(
            collect_official_deadline(
                html, now=NOW,
                source_url="https://www.example.edu/graduate/applications-and-admissions-faq",
            )[0],
            "verified",
        )

    def test_ucla_economics_grad_major_requirements_prints_dated_phd_cutoff(self):
        html = (
            "<h1>2027-2028 Admission Requirements for the Graduate Major in Economics</h1>"
            "<h3>Admissions Requirements for the Graduate Major in Economics</h3>"
            "<h3>APPLYING</h3>"
            "<p>After exploring options, follow our application instructions.</p>"
            "<h3>Deadlines to apply</h3><p>December 1, 2026</p>"
            "<h3>Program Name</h3><p>Economics</p>"
            "<h3>Leading to the degree of</h3>"
            "<p>M.A., Ph.D. Admits only Ph.D. applicants.</p>"
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=UCLA_REQUIREMENTS)[:2],
            ("verified", "2026-12-01"),
        )

    def test_ucla_other_graduate_major_cannot_use_its_deadline(self):
        html = (
            "<h1>2027-2028 Admission Requirements for the Graduate Major in Sociology</h1>"
            "<h3>Admissions Requirements for the Graduate Major in Sociology</h3>"
            "<h3>Deadlines to apply</h3><p>December 1, 2026</p>"
            "<h3>Program Name</h3><p>Sociology</p>"
            "<h3>Leading to the degree of</h3>"
            "<p>Ph.D. Admits only Ph.D. applicants.</p>"
            "<p>Economics is offered by a different department.</p>"
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=UCLA_REQUIREMENTS)[0],
            "verified",
        )

    def test_ucla_masters_only_requirements_cannot_be_promoted(self):
        html = (
            "<h1>2027-2028 Admission Requirements for the Graduate Major in Economics</h1>"
            "<h3>Deadlines to apply</h3><p>December 1, 2026</p>"
            "<h3>Program Name</h3><p>Economics</p>"
            "<h3>Leading to the degree of</h3>"
            "<p>M.A. Master's applicants only.</p>"
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=UCLA_REQUIREMENTS)[0],
            "verified",
        )

    def test_full_opt_in_review_includes_new_official_leads_and_ambiguous_pages(self):
        root = Path(__file__).resolve().parents[2]
        seeds = json.loads(
            (root / "config/phd_admissions_seeds.json").read_text(encoding="utf-8")
        )
        public = json.loads(
            (root / "docs/data/phd_admissions.json").read_text(encoding="utf-8")
        )
        candidate_states = {"no_explicit_deadline", "ambiguous_deadline", "unverified"}
        target_urls = {
            row["official_programme_url"] for row in public["programmes"]
            if row["status"] in candidate_states
        }
        self.assertGreaterEqual(len(target_urls), 3)
        seen = []

        def fetch(url, *, now):
            seen.append(url)
            return {"status": "no_explicit_deadline"}

        updated = refresh_inconclusive(
            seeds, public, now=NOW, batch_size=40, fetcher=fetch,
        )
        self.assertEqual(len(seen), len(target_urls))
        self.assertEqual(set(seen), target_urls)
        self.assertEqual(len(updated["programmes"]), len(seeds["programmes"]))
        self.assertFalse(any(
            url in seen for url in (
                row["official_programme_url"] for row in public["programmes"]
                if row["status"] in {"robots_unavailable", "robots_disallowed",
                                     "fetch_failed", "unsafe_redirect", "verified"}
            )
        ))

    def test_ucla_first_page_discovers_same_host_economics_requirements(self):
        initial = (
            "<h1>Economics</h1><h2>Graduate Program: Economics</h2>"
            "<p>Doctor of Philosophy (Ph.D.)</p>"
            '<a href="/requirements/?app=admission&amp;major=0246">'
            "Admission Requirements</a>"
        )
        detail = (
            "<h1>2027-2028 Admission Requirements for the Graduate Major in Economics</h1>"
            "<h3>Deadlines to apply</h3><p>December 1, 2026</p>"
            "<h3>Program Name</h3><p>Economics</p>"
            "<h3>Leading to the degree of</h3>"
            "<p>M.A., Ph.D. Admits only Ph.D. applicants.</p>"
        )
        docs = {UCLA: (initial, UCLA), UCLA_REQUIREMENTS: (detail, UCLA_REQUIREMENTS)}
        result = investigate_official_pages(
            UCLA, now=NOW,
            fetch_html=lambda url: docs[url],
            robots_allowed=lambda url: url in docs,
            max_pages=2,
        )
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["deadline_iso"], "2026-12-01")
        self.assertEqual(result["evidence_url"], UCLA_REQUIREMENTS)


if __name__ == "__main__":
    unittest.main()
