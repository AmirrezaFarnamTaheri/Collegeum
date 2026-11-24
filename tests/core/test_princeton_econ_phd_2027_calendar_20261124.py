"""Princeton's Graduate School publishes an explicit 2026 calendar for Fall 2027.

The department's yearless December 1 is not sufficient evidence alone. The
central graduate admissions page identifies ALL deadlines as 2026 calendar
dates and places Economics in the December 1 group. Never extrapolate a
year from an intake or carry an adjacent subject's deadline across groups.
"""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tools.update_phd_admissions import collect_official_deadline, validate_catalogues

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
PRINCETON = "https://gradschool.princeton.edu/admission-onboarding/prepare/application-deadlines"
OLD = "https://economics.princeton.edu/graduate-program/phd-admissions/"


def princeton_calendar(
    *, year_sentence: bool = True, economics_in_dec1: bool = True,
    economics_in_dec15: bool = False, date: str = "December 1",
    year: int = 2026,
) -> str:
    year_note = (
        "While the application is for Fall 2027 enrollment, "
        f"all associated deadlines fall within the {year} calendar year "
        f"(e.g., November 15, {year}) and are subject to change until September 1."
        if year_sentence else ""
    )
    economics = "<li>Economics</li>" if economics_in_dec1 else ""
    economics_later = "<li>Economics</li>" if economics_in_dec15 else ""
    return (
        "<h1>Application Deadlines</h1>"
        "<p>The application for Fall 2027 is now open.</p>"
        "<h2>Deadlines</h2>"
        "<p>Your application and all required supporting materials must be "
        "submitted by the deadline listed below for the program "
        "to which you are applying. Late applications are not accepted.</p>"
        f"<p>{year_note}</p>"
        "<p>Deadline | Fields of Study</p>"
        "<div>November 15</div><ul><li>Psychology</li></ul>"
        f"<div>{date}</div>"
        "<ul><li>Art and Archeology</li><li>Biophysics</li>"
        "<li>East Asian Studies</li>" + economics
        + "<li>Ecology and Evolutionary Biology</li>"
        "<li>History of Science</li></ul>"
        "<div>December 15</div><ul><li>Anthropology</li>"
        + economics_later
        + "<li>Finance</li><li>Mathematics</li></ul>"
        "<div>December 21</div><ul><li>Architecture</li></ul>"
    )


class PrincetonEconomicsGraduateCalendarTests(unittest.TestCase):
    def test_source_is_the_schoolwide_current_year_calendar_not_yearless_department(self):
        seeds = json.loads(
            (ROOT / "config/phd_admissions_seeds.json").read_text(encoding="utf-8")
        )
        public = json.loads(
            (ROOT / "docs/data/phd_admissions.json").read_text(encoding="utf-8")
        )
        validate_catalogues(seeds, public)
        seed = next(x for x in seeds["programmes"]
                    if x["institution"] == "Princeton University")
        record = next(x for x in public["programmes"]
                      if x["institution"] == "Princeton University")
        self.assertEqual(seed["official_programme_url"], PRINCETON)
        self.assertEqual(record["official_programme_url"], PRINCETON)
        if record["status"] == "verified":
            self.assertEqual(record["deadline_iso"], "2026-12-01")
            self.assertEqual(record["evidence_url"], PRINCETON)
        else:
            self.assertIsNone(record["deadline_iso"])

    def test_explicit_calendar_year_and_economics_row_verify(self):
        status, deadline, excerpt = collect_official_deadline(
            princeton_calendar(), now=NOW, source_url=PRINCETON,
        )
        self.assertEqual((status, deadline), ("verified", "2026-12-01"))
        self.assertIn("Economics", excerpt)
        self.assertIn("2026", excerpt)

    def test_calendar_year_is_required_not_inferred_from_fall_2027(self):
        status, deadline, _ = collect_official_deadline(
            princeton_calendar(year_sentence=False), now=NOW, source_url=PRINCETON,
        )
        self.assertNotEqual(status, "verified")
        self.assertIsNone(deadline)

    def test_only_economics_in_matching_december_group_is_evidence(self):
        for page in (
            princeton_calendar(economics_in_dec1=False),
            princeton_calendar(economics_in_dec1=False,
                               economics_in_dec15=True),
            princeton_calendar(year=2025),
            princeton_calendar(date="December 1, 2027"),
        ):
            with self.subTest(page=page):
                self.assertNotEqual(
                    collect_official_deadline(page, now=NOW,
                                              source_url=PRINCETON)[0],
                    "verified",
                )

    def test_cross_school_or_old_department_url_never_lends_calendar_year(self):
        for url in (
            OLD,
            "https://www.princeton.edu/admission-onboarding/prepare/application-deadlines",
            "https://other.example.edu/admission-onboarding/prepare/application-deadlines",
        ):
            with self.subTest(url=url):
                self.assertNotEqual(
                    collect_official_deadline(princeton_calendar(), now=NOW,
                                              source_url=url)[0],
                    "verified",
                )

    def test_conflicting_economics_groups_cannot_silently_pick_one(self):
        self.assertEqual(
            collect_official_deadline(
                princeton_calendar(economics_in_dec15=True),
                now=NOW, source_url=PRINCETON,
            )[0],
            "ambiguous_deadline",
        )


if __name__ == "__main__":
    unittest.main()
