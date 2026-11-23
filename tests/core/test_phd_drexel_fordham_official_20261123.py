"""Current-cycle schoolwide economics doctoral deadlines with exact programme scope.

Official institutional HTML structure is simulated for offline tests. The live
catalogue is never promoted by a fixture or third-party date.
"""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.update_phd_admissions import collect_official_deadline

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)
DREXEL = "https://www.lebow.drexel.edu/admissions/doctorate/admission-standards"
FORDHAM = ("https://www.fordham.edu/graduate-school-of-arts-and-sciences/"
           "admissions/how-to-apply/application-deadlines/")


def drexel_page(*, econ: bool = True, cutoff: str = "Dec. 15, 2026",
                next_year: bool = True, another: str = "") -> str:
    econ_anchor = (
        '<a href="/academics/phd-economics">PhD in Economics</a>'
        if econ else '<a href="/academics/phd-marketing">PhD in Marketing</a>'
    )
    return (
        "<h1>PhD Application Requirements and Deadlines</h1>"
        "<p>Drexel LeBow's doctoral program offers a research-driven curriculum.</p>"
        + econ_anchor
        + "<h2>Application Deadline</h2>"
        f"<ul><li>{cutoff} — Application deadline for "
        + ("Fall 2027" if next_year else "Fall 2025")
        + "</li></ul>"
        "<h2>Admissions Requirements</h2>"
        "<p>All PhD applicants submit transcripts.</p>"
        + another
    )


def fordham_page(*, econ: bool = True, cutoff: str = "January 8, 2027",
                 phd: bool = True, extra: str = "") -> str:
    anchor = (
        '<a href="/academics/departments/economics/graduate-studies/phd-in-economics/">'
        "Economics</a>" if econ
        else ('<a href="/academics/departments/economics/graduate-studies/"'
              'master-of-arts-in-economics/">Economics (MA)</a>')
    )
    doctoral_rows = (
        '<table><tr><th>Programs</th><th>Deadlines</th></tr>'
        '<tr><td>Computer Science, ' + anchor
        + ', English, History, Philosophy</td>'
        f'<td>{cutoff}</td></tr></table>'
    )
    masters_rows = (
        "<h2>Master's Program Deadlines</h2>"
        '<table><tr><th>Programs</th><th>Deadlines</th></tr>'
        '<tr><td>Economics (MA)</td><td>July 30, 2027</td></tr></table>'
    )
    return (
        "<h1>GSAS Application Deadlines</h1>"
        "<h2>2027 Admissions</h2>"
        "<p>Application deadlines vary by program and entry term.</p>"
        "<h2>Application Deadlines</h2>"
        "<h3>Fall 2027 Entry</h3>"
        + (doctoral_rows if phd else masters_rows)
        + (masters_rows if phd else "") + extra
    )


class EconomicsDoctoralSchoolwideDeadlinesTests(unittest.TestCase):
    def test_drexel_application_date_applies_to_named_economics_phd(self):
        status, deadline, excerpt = collect_official_deadline(
            drexel_page(), now=NOW, source_url=DREXEL,
        )
        self.assertEqual((status, deadline), ("verified", "2026-12-15"))
        self.assertIn("Dec. 15, 2026", excerpt)

    def test_drexel_rejects_unrelated_field_yearless_or_wrong_date(self):
        for html, url in (
            (drexel_page(econ=False), DREXEL),
            (drexel_page(cutoff="Dec. 15"), DREXEL),
            (drexel_page(next_year=False), DREXEL),
            (drexel_page(), "https://www.lebow.drexel.edu/admissions/undergraduate/admission-standards"),
            (drexel_page(), "https://unrelated.example.edu/admissions/doctorate/admission-standards"),
        ):
            with self.subTest(url=url, html=html):
                self.assertNotEqual(
                    collect_official_deadline(html, now=NOW, source_url=url)[0],
                    "verified",
                )

    def test_drexel_conflicting_current_year_cutoffs_ambiguous(self):
        html = drexel_page(another=(
            "<p>January 3, 2027 — Application deadline for Fall 2027</p>"
        ))
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=DREXEL)[0],
            "ambiguous_deadline",
        )

    def test_fordham_named_economics_phd_row_matches_correct_final_cutoff(self):
        status, deadline, excerpt = collect_official_deadline(
            fordham_page(), now=NOW, source_url=FORDHAM,
        )
        self.assertEqual((status, deadline), ("verified", "2027-01-08"))
        self.assertIn("Economics", excerpt)

    def test_fordham_masters_and_unrelated_phd_deadline_not_promoted(self):
        for html, url in (
            (fordham_page(econ=False), FORDHAM),
            (fordham_page(phd=False), FORDHAM),
            (fordham_page(cutoff="January 8"), FORDHAM),
            (fordham_page(), "https://www.fordham.edu/academics/undergraduate/admissions/"),
            (fordham_page(), "https://other.example.edu/graduate-school-of-arts-and-sciences/admissions/how-to-apply/application-deadlines/"),
        ):
            with self.subTest(url=url, html=html):
                self.assertNotEqual(
                    collect_official_deadline(html, now=NOW, source_url=url)[0],
                    "verified",
                )

    def test_fordham_conflicting_economics_phd_rows_are_ambiguous(self):
        alternate = (
            '<table><tr><th>Programs</th><th>Deadlines</th></tr>'
            '<tr><td><a href="/academics/departments/economics/graduate-studies/phd-in-economics/">'
            'Economics</a></td><td>January 15, 2027</td></tr></table>'
        )
        self.assertEqual(
            collect_official_deadline(
                fordham_page(extra=alternate), now=NOW, source_url=FORDHAM,
            )[0],
            "ambiguous_deadline",
        )


if __name__ == "__main__":
    unittest.main()
