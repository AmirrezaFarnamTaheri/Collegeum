"""Cambridge Economics PhD source correction and deadline-role regression tests.

The MPhil in Economic Research has its own admissions page. No Master's
deadline, funding deadline, or application opening date can be promoted as
the PhD submission cutoff. Test data is synthetic: only the official-source
checker may publish corroborated observations.
"""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tools.update_phd_admissions import collect_official_deadline, validate_catalogues

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 24, 9, tzinfo=UTC)
PHD = "https://www.postgraduate.study.cam.ac.uk/courses/directory/ececpdpec"
MPHIL = "https://www.postgraduate.study.cam.ac.uk/courses/directory/ececmpmer"


def cambridge_phd_page(
    *, degree: str = "PhD in Economics", closing: str = "Feb. 2, 2027",
    extra: str = "",
) -> str:
    return (
        f"<h1>{degree}</h1>"
        "<p>Research doctorate at the Faculty of Economics.</p>"
        "<h2>Key Information</h2>"
        "<p>Doctor of Philosophy (PhD)</p>"
        "<p>Faculty of Economics</p>"
        "<div>Dates and deadlines:</div>"
        "<div>Michaelmas 2027</div>"
        "<div>Applications open</div><div>Sep. 9, 2026</div>"
        f"<div>Application deadline</div><div>{closing}</div>"
        "<div>Course starts</div><div>Oct. 1, 2027</div>"
        "<h3>Funding Deadlines</h3>"
        "<div>Course Funding Deadline</div><div>Dec. 8, 2026</div>"
        "<div>Gates Cambridge US round only</div><div>Oct. 14, 2026</div>"
        + extra
    )


class CambridgePhdEconomicsSourceTests(unittest.TestCase):
    def test_catalogue_uses_official_economics_phd_not_separate_mphil_page(self):
        seeds = json.loads(
            (ROOT / "config/phd_admissions_seeds.json").read_text(encoding="utf-8")
        )
        public = json.loads(
            (ROOT / "docs/data/phd_admissions.json").read_text(encoding="utf-8")
        )
        validate_catalogues(seeds, public)
        seed = next(
            x for x in seeds["programmes"]
            if x["institution"] == "University of Cambridge"
        )
        record = next(
            x for x in public["programmes"]
            if x["institution"] == "University of Cambridge"
        )
        self.assertEqual(seed["official_programme_url"], PHD)
        self.assertEqual(record["official_programme_url"], PHD)
        if record["status"] == "verified":
            self.assertEqual(record["deadline_iso"], "2027-02-02")
            self.assertTrue(record["evidence_url"].startswith(PHD))
        else:
            self.assertIsNone(record["deadline_iso"])
            self.assertIsNone(record["evidence_url"])

    def test_phd_application_deadline_not_course_start_or_earlier_funding(self):
        status, day, excerpt = collect_official_deadline(
            cambridge_phd_page(), now=NOW, source_url=PHD,
        )
        self.assertEqual((status, day), ("verified", "2027-02-02"))
        self.assertIn("Feb. 2, 2027", excerpt)

    def test_mphil_directory_must_not_be_counted_as_phd(self):
        html = cambridge_phd_page(degree="MPhil in Economic Research")
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=MPHIL)[0],
            "verified",
        )

    def test_yearless_expired_unrelated_and_wrong_host_fail_closed(self):
        for html, url in (
            (cambridge_phd_page(closing="Feb. 2"), PHD),
            (cambridge_phd_page(closing="Feb. 2, 2025"), PHD),
            (cambridge_phd_page(degree="MPhil in Economic Research"), PHD),
            (cambridge_phd_page(), MPHIL),
            (cambridge_phd_page(), "https://not-cambridge.example.edu/courses/directory/ececpdpec"),
        ):
            with self.subTest(url=url, html=html):
                self.assertNotEqual(
                    collect_official_deadline(html, now=NOW, source_url=url)[0],
                    "verified",
                )

    def test_conflicting_current_year_phd_application_dates_are_ambiguous(self):
        html = cambridge_phd_page(extra=(
            "<p>Dates and deadlines: Michaelmas 2027 "
            "Application deadline Feb. 10, 2027 Course starts Oct. 1, 2027.</p>"
        ))
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=PHD)[0],
            "ambiguous_deadline",
        )

    def test_same_phd_deadline_on_official_application_subpage(self):
        self.assertEqual(
            collect_official_deadline(
                cambridge_phd_page(), now=NOW, source_url=PHD + "/apply",
            )[:2],
            ("verified", "2027-02-02"),
        )


if __name__ == "__main__":
    unittest.main()
