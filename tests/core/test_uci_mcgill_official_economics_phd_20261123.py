"""Official source regressions for McGill and UC Irvine Economics doctoral admissions.

Institution-owned page layouts are modelled with synthetic offline HTML.
Only the live, robots-aware university monitor may publish a verified date.
"""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tools.update_phd_admissions import collect_official_deadline, validate_catalogues

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]
MCGILL = "https://www.mcgill.ca/economics/graduates/admissions"
UCI = "https://www.gradstudies.socsci.uci.edu/admissions/overview.php"


def mcgill_page(
    *, phd_link: bool = True, date_text: str = "JANUARY 15, 2027",
    supplementary: str = "January 15, 2027", extra: str = "",
) -> str:
    link = (
        '<a href="/economics/graduates/phd-program">PhD Program</a>'
        if phd_link else '<a href="/economics/graduates/ma-program">MA Program</a>'
    )
    return (
        "<h1>Admissions</h1><nav>" + link + "</nav>"
        "<h2>Admission Application to the Department of Economics</h2>"
        "<p>Applications for graduate study at McGill University.</p>"
        "<h2>Application and Required Documents</h2>"
        "<p>Documents must be uploaded through the McGill system.</p>"
        "<h2>Application Deadline</h2>"
        "<p>Deadline for Receipt of Complete Application, except in "
        f"extraordinary circumstances, is {date_text}.</p>"
        "<p>Please note that the Department ONLY accepts applications "
        "for September registration.</p>"
        "<p>The final deadline with all supporting documents to be uploaded "
        f"on McGill's Application Portal is {supplementary}.</p>" + extra
    )


def uci_page(
    *, label: str = "Economics", date_text: str = "December 1, 2026",
    fall: str = "Fall 2027", extra: str = "",
    phd_scope: bool = True,
) -> str:
    scope = (
        "<p>With the exception of the DASA and PPE Master's degree programs, "
        "we accept applications for and make offers only for Ph.D. admission.</p>"
        if phd_scope else
        "<p>We offer only Master's admissions for all programmes.</p>"
    )
    return (
        "<h1>Admissions</h1>"
        "<p>The School of Social Sciences accepts applications for the "
        "fall quarter only.</p>"
        "<p>Complete application packets must be received by the "
        "department's application deadline.</p>"
        f"<h2>Application Deadlines - {fall}</h2>"
        "<div>Anthropology</div><div>December 15, 2026</div>"
        "<div>Cognitive Science</div><div>December 2, 2026</div>"
        f"<div>{label}</div><div>{date_text}</div>"
        "<div>Global Studies</div><div>January 8, 2027</div>"
        + extra
        + "<div>Social Science MA (Demographic and Social Analysis): "
        "June 1, 2027</div>"
        "<div>Social Science MA (Philosophy, Political Science & Economics): "
        "April 15, 2027</div>"
        "<h2>Before You Apply</h2>" + scope
    )


class EconomicsInstitutionalSourcesTests(unittest.TestCase):
    def test_mcgill_full_year_deadline_with_economics_phd_scope(self):
        self.assertEqual(
            collect_official_deadline(mcgill_page(), now=NOW,
                                      source_url=MCGILL)[:2],
            ("verified", "2027-01-15"),
        )

    def test_mcgill_cannot_inherit_masters_unrelated_or_yearless_dates(self):
        for html, url in (
            (mcgill_page(phd_link=False), MCGILL),
            (mcgill_page(date_text="JANUARY 15", supplementary="January 15"), MCGILL),
            (mcgill_page(), "https://www.mcgill.ca/management/graduate/admissions"),
            (mcgill_page(), "https://unrelated.example.edu/economics/graduates/admissions"),
        ):
            with self.subTest(url=url, html=html):
                self.assertNotEqual(
                    collect_official_deadline(html, now=NOW, source_url=url)[0],
                    "verified",
                )

    def test_mcgill_conflicting_current_year_app_cutoffs_are_ambiguous(self):
        html = mcgill_page(extra=(
            "<p>Deadline for Receipt of Complete Application "
            "is January 20, 2027.</p>"
        ))
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=MCGILL)[0],
            "ambiguous_deadline",
        )

    def test_uci_schoolwide_economics_phd_named_row_current_cycle(self):
        status, cutoff, excerpt = collect_official_deadline(
            uci_page(), now=NOW, source_url=UCI,
        )
        self.assertEqual((status, cutoff), ("verified", "2026-12-01"))
        self.assertIn("Economics", excerpt)
        self.assertIn("December 1, 2026", excerpt)

    def test_uci_masters_dates_and_neighbouring_phd_dates_not_misattributed(self):
        for html, url in (
            (uci_page(label="Language Science"), UCI),
            (uci_page(date_text="December 1"), UCI),
            (uci_page(phd_scope=False), UCI),
            (uci_page(), "https://www.economics.uci.edu/grad/admissions.php"),
            (uci_page(), "https://unrelated.example.edu/admissions/overview.php"),
        ):
            with self.subTest(url=url, html=html):
                self.assertNotEqual(
                    collect_official_deadline(html, now=NOW, source_url=url)[0],
                    "verified",
                )

    def test_uci_conflicting_economics_deadlines_fail_closed(self):
        html = uci_page(extra=(
            "<div>Economics</div><div>December 15, 2026</div>"
        ))
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=UCI)[0],
            "ambiguous_deadline",
        )

    def test_uci_rejects_wrong_intake_with_current_calendar_date(self):
        self.assertNotEqual(
            collect_official_deadline(
                uci_page(fall="Fall 2025"), now=NOW, source_url=UCI,
            )[0],
            "verified",
        )

    def test_source_repair_preserves_entire_official_only_catalogue(self):
        seeds = json.loads(
            (ROOT / "config/phd_admissions_seeds.json").read_text(encoding="utf-8")
        )
        public = json.loads(
            (ROOT / "docs/data/phd_admissions.json").read_text(encoding="utf-8")
        )
        validate_catalogues(seeds, public)
        self.assertEqual(len(seeds["programmes"]), 251)
        self.assertEqual(len(public["programmes"]), 251)
        seed = next(p for p in seeds["programmes"] if p["institution"] == "UC, Irvine")
        row = next(p for p in public["programmes"] if p["institution"] == "UC, Irvine")
        self.assertEqual(seed["official_programme_url"], UCI)
        self.assertEqual(row["official_programme_url"], UCI)
        if row["status"] == "verified":
            self.assertEqual(row["deadline_iso"], "2026-12-01")
            self.assertEqual(row["evidence_url"], UCI)
        else:
            self.assertIsNone(row["deadline_iso"])


if __name__ == "__main__":
    unittest.main()
