"""Fordham's official 2027 PhD deadline group is not necessarily an HTML table.

The public Fordham GSAS page renders a group of programmes in a styled grid,
with distinct PhD and Master's sections. Require an institutional PhD link
within the doctoral entry and a full-year date adjacent to its group. Never
borrow July deadlines or Master's priority dates.
"""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.update_phd_admissions import collect_official_deadline

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)
FORDHAM = (
    "https://www.fordham.edu/graduate-school-of-arts-and-sciences/"
    "admissions/how-to-apply/application-deadlines/"
)
PHD = "/academics/departments/economics/graduate-studies/phd-in-economics/"
MA = "/academics/departments/economics/graduate-studies/master-of-arts-in-economics/"


def fordham_layout(
    *,
    cutoff: str = "January 8, 2027",
    phd_link: bool = True,
    include_economics: bool = True,
    masters_only: bool = False,
    extra_doctoral_dates: str = "",
) -> str:
    economics = (
        f'<a href="{PHD}">Economics</a>'
        if phd_link else "Economics"
    ) if include_economics else "Econometrics"
    if masters_only:
        economics = f'<a href="{MA}">Economics (MA)</a>'
    doctoral = (
        "<div class='admissions-degree'>Fall 2027 Entry</div>"
        "<div role='table'><div role='row'>Programs Deadlines</div>"
        "<div role='row'>Clinical Psychology November 16, 2026</div>"
        "<div role='row'>Applied Developmental Psychology November 30, 2026</div>"
        "<div role='row'>Biological Sciences Computer Science "
        + economics
        + " English History Philosophy Theology "
        + cutoff
        + extra_doctoral_dates
        + "</div></div>"
    )
    masters = (
        "<div class='masters-group'>Spring 2027 Entry</div>"
        "<p>Deadline: December 1, 2026. Applies to all master's programs.</p>"
        "<div>Fall 2027 Entry</div><div>Programs Deadlines</div>"
        f'<a href="{MA}">Economics (MA)</a>'
        "<p>Priority deadline January 8, 2027</p>"
        "<p>General Consideration March 31, 2027</p>"
        "<p>Final deadline July 30, 2027</p>"
    )
    return (
        "<h1>GSAS Application Deadlines</h1>"
        "<h2>2027 Admissions</h2>"
        "<p>Application deadlines vary by program and entry term.</p>"
        "<h3>Application Deadlines</h3>"
        + doctoral + masters
    )


class FordhamRealWorldGroupedLayoutTests(unittest.TestCase):
    def test_doctoral_group_without_html_table_still_supplies_economics_cutoff(self):
        status, deadline, excerpt = collect_official_deadline(
            fordham_layout(), now=NOW, source_url=FORDHAM,
        )
        self.assertEqual((status, deadline), ("verified", "2027-01-08"))
        self.assertIn("January 8, 2027", excerpt)
        self.assertIn("Economics", excerpt)

    def test_masters_priority_and_final_dates_cannot_replace_phd_cutoff(self):
        status, deadline, _excerpt = collect_official_deadline(
            fordham_layout(), now=NOW, source_url=FORDHAM,
        )
        self.assertEqual((status, deadline), ("verified", "2027-01-08"))

    def test_no_phd_link_or_wrong_doctoral_programme_cannot_verify(self):
        for html in (
            fordham_layout(phd_link=False),
            fordham_layout(include_economics=False),
            fordham_layout(masters_only=True),
            fordham_layout(cutoff="January 8"),
        ):
            with self.subTest(html=html):
                status, date, _ = collect_official_deadline(
                    html, now=NOW, source_url=FORDHAM,
                )
                self.assertNotEqual(status, "verified")
                self.assertIsNone(date)

    def test_doctoral_economics_link_outside_date_group_does_not_transfer_cutoff(self):
        html = fordham_layout(include_economics=False) + (
            f'<footer><a href="{PHD}">Economics</a></footer>'
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=FORDHAM)[0],
            "verified",
        )

    def test_university_and_route_must_match_primary_source(self):
        for url in (
            "https://www.fordham.edu/academics/undergraduate/admissions/",
            "https://fordham.university.example.com/graduate-school-of-arts-and-sciences/"
            "admissions/how-to-apply/application-deadlines/",
        ):
            with self.subTest(url=url):
                self.assertNotEqual(
                    collect_official_deadline(fordham_layout(), now=NOW,
                                              source_url=url)[0],
                    "verified",
                )

    def test_competing_current_doctoral_dates_fail_closed(self):
        html = fordham_layout(
            extra_doctoral_dates=" Alternate Economics PhD deadline January 15, 2027"
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=FORDHAM)[0],
            "ambiguous_deadline",
        )

    def test_neighbouring_phd_group_cutoff_cannot_be_misattributed(self):
        html = (
            "<h1>GSAS Application Deadlines</h1>"
            "<h2>2027 Admissions</h2><h3>Application Deadlines</h3>"
            "<div>Fall 2027 Entry</div>"
            "<div>Clinical Psychology November 16, 2026</div>"
            "<div>Biological Sciences Computer Science English History "
            "Philosophy Theology January 8, 2027</div>"
            f'<div>Spring 2027 Entry</div><a href="{PHD}">Economics</a>'
            "<p>Economics (MA) Final deadline July 30, 2027.</p>"
        )
        self.assertNotEqual(
            collect_official_deadline(html, now=NOW, source_url=FORDHAM)[0],
            "verified",
        )


if __name__ == "__main__":
    unittest.main()
