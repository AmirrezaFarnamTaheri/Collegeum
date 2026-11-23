"""Current-cycle Charles University Economics and Finance doctoral source repair.

The institute's IES Faculty of Social Sciences page is institution-owned;
this suite never treats a historical application date or a search result as
an independently checked catalogue deadline.
"""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tools.update_phd_admissions import collect_official_deadline, validate_catalogues

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)
SOURCE = "https://ies.fsv.cuni.cz/en/admissions/admissions/doctoral-degree-economics-and-finance"
ROOT = Path(__file__).resolve().parents[2]


def official_html(*, heading: str = "Doctoral degree Economics and Finance",
                  future: str = "30 April 2027", doctoral: bool = True,
                  other: str = "") -> str:
    identity = (
        "<p>For the next PhD admission intake round open positions "
        "by IES faculty members will be announced.</p>"
        "<h2>About the PhD in Economics and Finance</h2>"
        "<p>The PhD program concentrates on economic theory and its applications.</p>"
        if doctoral else "<p>This is a Master's admissions programme.</p>"
    )
    return (
        f"<h1>{heading}</h1>"
        "<h2>Application</h2>"
        "<p>The application process for the 2026/2027 academic year is closed.</p>"
        + identity
        + "<h2>Application</h2>"
        "<p>The day of the deadline to submit your application is April 30, 2026.</p>"
        "<h2>Conditions for applicants</h2>"
        "<p>The conditions on how to apply will be announced as of January 1st 2027. "
        f"The admission proces will open as of this day and will last to {future}.</p>"
        + other
    )


class CharlesDoctoralSourceRepairTests(unittest.TestCase):
    def test_new_official_host_and_catalogue_are_coherent(self):
        seeds = json.loads(
            (ROOT / "config/phd_admissions_seeds.json").read_text(encoding="utf-8")
        )
        public = json.loads(
            (ROOT / "docs/data/phd_admissions.json").read_text(encoding="utf-8")
        )
        validate_catalogues(seeds, public)
        seed = next(x for x in seeds["programmes"]
                    if x["institution"] == "Charles University")
        entry = next(x for x in public["programmes"]
                     if x["institution"] == "Charles University")
        self.assertEqual(seed["official_programme_url"], SOURCE)
        self.assertEqual(entry["official_programme_url"], SOURCE)
        self.assertNotEqual(entry["status"], "unsafe_redirect")
        if entry["status"] == "verified":
            self.assertEqual(entry["evidence_url"], SOURCE)
            self.assertEqual(entry["deadline_iso"], "2027-04-30")
        else:
            self.assertIsNone(entry["deadline_iso"])
            self.assertIsNone(entry.get("evidence_url"))

    def test_new_phd_intake_closing_is_explicit_not_prior_stale_year(self):
        status, day, excerpt = collect_official_deadline(
            official_html(), now=NOW, source_url=SOURCE,
        )
        self.assertEqual((status, day), ("verified", "2027-04-30"))
        self.assertIn("30 April 2027", excerpt)

    def test_stale_yearless_or_wrong_programme_dates_never_promoted(self):
        for html, url in (
            (official_html(future="30 April"), SOURCE),
            (official_html(future="30 April 2026"), SOURCE),
            (official_html(doctoral=False), SOURCE),
            (official_html(heading="Master in Economics and Finance"), SOURCE),
            (official_html(), "https://fsv.cuni.cz/en/admissions/phd-programmes/economics-and-finance"),
            (official_html(), "https://fake.example.edu/en/admissions/admissions/doctoral-degree-economics-and-finance"),
        ):
            with self.subTest(html=html, url=url):
                self.assertNotEqual(
                    collect_official_deadline(html, now=NOW, source_url=url)[0],
                    "verified",
                )

    def test_conflicting_new_doctoral_closing_dates_are_ambiguous(self):
        html = official_html(other=(
            "<p>The admission process will open as of January 1st 2027 "
            "and will last to 15 May 2027.</p>"
        ))
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=SOURCE)[0],
            "ambiguous_deadline",
        )


if __name__ == "__main__":
    unittest.main()
