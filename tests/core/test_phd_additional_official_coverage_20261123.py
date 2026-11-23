"""Regression tests for missed official doctoral deadlines and relevant-link budgets.

Synthetic HTML mirrors layouts independently seen on current university pages.
No third-party date is accepted into the published admissions catalogue.
"""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.update_phd_admissions import collect_official_deadline, select_official_links

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)
STERN = "https://www.stern.nyu.edu/programs-admissions/phd/admissions/how-to-apply"
LBS = "https://www.london.edu/phd/how-to-apply"


def stern_page(*, field: str = "Economics", cutoff: str = "December 15, 2026") -> str:
    return (
        "<h1>How To Apply</h1>"
        "<p>Our Fall 2027 application is now open. "
        f"The application deadline is {cutoff} at 11:59PM ET.</p>"
        "<h2>Application Requirements</h2>"
        "<p>All applicants to the NYU Stern School of Business PhD Program "
        "are required to submit a complete application.</p>"
        "<table><tr><th>Area of Study</th><th>Preferred Test</th></tr>"
        f"<tr><td>{field}</td><td>GRE</td></tr></table>"
    )


def lbs_page(*, field: str = "Economics", cutoff: str = "6 January 2027",
             extra: str = "") -> str:
    return (
        "<h1>How to apply</h1><h2>Application timeline</h2>"
        "<p>Intake for the seven PhD Programmes / Subject Areas at LBS "
        "all follow the same common annual recruiting cycle and no "
        "applications are ever considered outside of this cycle.</p>"
        "<p>The following dates apply for September 2027 entry.</p>"
        "<h2>Apply now</h2>"
        f'<a href="https://apply.interfolio.com/123">{field}</a>'
        "<h2>How to apply FAQs</h2>"
        f"<p>Applications are open from 1 September 2026 to {cutoff}. "
        "Please note that we do not accept late applications.</p>"
        + extra
    )


class NewlySupportedOfficialDeadlinesTests(unittest.TestCase):
    def test_stern_common_phd_application_deadline_explicitly_covers_economics(self):
        self.assertEqual(
            collect_official_deadline(stern_page(), now=NOW, source_url=STERN)[:2],
            ("verified", "2026-12-15"),
        )

    def test_stern_shared_deadline_requires_economics_in_doctoral_field_table(self):
        for html, url in (
            (stern_page(field="Finance"), STERN),
            (stern_page(), "https://www.stern.nyu.edu/programs-admissions/mba/admissions/how-to-apply"),
            (stern_page(), "https://other.example.edu/programs-admissions/phd/admissions/how-to-apply"),
            (stern_page(cutoff="December 15"), STERN),
        ):
            with self.subTest(url=url, html=html):
                status, deadline, _ = collect_official_deadline(
                    html, now=NOW, source_url=url,
                )
                self.assertNotEqual(status, "verified")
                self.assertIsNone(deadline)

    def test_stern_conflicting_full_year_application_deadlines_fail_closed(self):
        html = stern_page() + (
            "<p>For international applicants, the application deadline "
            "is January 10, 2027.</p>"
        )
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=STERN)[0],
            "ambiguous_deadline",
        )

    def test_lbs_shared_doctoral_application_period_has_explicit_closing_date(self):
        status, cutoff, excerpt = collect_official_deadline(
            lbs_page(), now=NOW, source_url=LBS,
        )
        self.assertEqual((status, cutoff), ("verified", "2027-01-06"))
        self.assertIn("6 January 2027", excerpt)
        self.assertNotIn("1 September 2026", excerpt[:25])

    def test_lbs_requires_named_economics_phd_and_explicit_full_year_closing(self):
        for html, url in (
            (lbs_page(field="Marketing"), LBS),
            (lbs_page(cutoff="6 January"), LBS),
            (lbs_page(), "https://www.london.edu/masters-degrees/masters-in-finance/apply"),
            (lbs_page(), "https://unrelated.example.edu/phd/how-to-apply"),
        ):
            with self.subTest(url=url, html=html):
                self.assertNotEqual(
                    collect_official_deadline(html, now=NOW, source_url=url)[0],
                    "verified",
                )

    def test_lbs_conflicting_full_year_application_periods_are_ambiguous(self):
        html = lbs_page(extra=(
            "<p>Applications are open from 1 September 2026 to 10 January 2027. "
            "Please note that we do not accept late applications.</p>"
        ))
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=LBS)[0],
            "ambiguous_deadline",
        )

    def test_link_budget_prefers_phd_over_hundreds_of_masters_navigation_links(self):
        navigation = "".join(
            f'<a href="/masters-degrees/degree-{i}/apply">How to apply</a>'
            for i in range(360)
        )
        html = (
            "<h1>PhD</h1>" + navigation
            + '<a href="/phd/how-to-apply">How to apply</a>'
            + '<a href="/phd/fees-and-funding">Fees and funding</a>'
        )
        urls = select_official_links(
            html, "https://www.london.edu/phd#howtoapply", max_links=2,
        )
        self.assertIn("https://www.london.edu/phd/how-to-apply", urls)
        self.assertTrue(all("/masters-degrees/" not in url for url in urls))

    def test_link_budget_rejects_non_phd_masters_and_summer_school_pages(self):
        html = (
            "<h1>PhD Programme</h1>"
            '<a href="/master-s-programs/master-economics-finance/admissions">'
            "Master Economics and Finance admissions</a>"
            '<a href="/hec-academy/summer-school/accounts-finance/admissions">'
            "Summer school admissions</a>"
            '<a href="/en/phd-program/apply">Doctoral applications</a>'
        )
        urls = select_official_links(
            html, "https://www.hec.edu/en/phd-program/admissions", max_links=2,
        )
        self.assertEqual(urls, ["https://www.hec.edu/en/phd-program/apply"])

    def test_official_masters_stage_phd_track_can_still_follow_admissions(self):
        track = "https://bse.eu/masters-degrees/economics-finance/upf-phd-track"
        html = (
            "<h1>UPF PhD Track</h1>"
            '<a href="/masters-degrees/admissions">Admissions to the PhD-track first year</a>'
        )
        self.assertEqual(
            select_official_links(html, track, max_links=1),
            ["https://bse.eu/masters-degrees/admissions"],
        )


if __name__ == "__main__":
    unittest.main()
