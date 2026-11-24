"""Kyoto's complete application is distinct from screening and document extras."""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.phd_admissions_asia import collect_deadline
from tools.update_phd_admissions import DATE_PATTERN, PageText, _parse_date

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
KYOTO = "https://www.econ.kyoto-u.ac.jp/kueac/application/doctoral/"
ROLE = (
    "Submission of Application Documents and Examination Fee Payment "
    "(via Online Application System)"
)


def kyoto(close="March 11 (1pm/Thurs) 2027", role=ROLE, extra=""):
    return (
        "<h1>Application Procedures for Doctoral Programme</h1>"
        "<p>International Graduate Programme for East Asia Sustainable "
        "Economic Development Studies</p>"
        "<p>Graduate School of Economics</p>"
        "<h3>Overall Schedule for Application and Selection (Date and Time : JST)</h3>"
        "<p>October 2027 intake</p><table>"
        "<tr><td>September 2026</td><td>Application Announcement</td></tr>"
        f"<tr><td>March 1 (9am/Mon) ～{close} “Strict Deadline”</td><td>{role}</td></tr>"
        "<tr><td>April 19 (3pm/Mon) 2027</td>"
        "<td>Announcement of Initial Screening Results</td></tr>"
        "<tr><td>June 11 (3pm/Fri) 2027</td>"
        "<td>Announcement of Final Screening Results</td></tr>"
        + extra + "</table>"
    )


def check(html, *, url=KYOTO, now=NOW):
    parser = PageText()
    parser.feed(html)
    return collect_deadline(
        parser, now=now, source_url=url, date_pattern=DATE_PATTERN, parse_date=_parse_date,
    )


class KyotoAdmissionsTests(unittest.TestCase):
    def test_table_closing_date_preserves_official_time_weekday_and_role(self):
        status, day, excerpt = check(kyoto())
        self.assertEqual((status, day), ("verified", "2027-03-11"))
        self.assertIn("March 11 (1pm/Thurs) 2027", excerpt)
        self.assertIn(ROLE, excerpt)
        self.assertLessEqual(len(excerpt), 180)

    def test_regular_spelled_date_still_requires_the_application_role(self):
        self.assertEqual(check(kyoto("March 11, 2027"))[:2], ("verified", "2027-03-11"))
        for role in (
            "Announcement of Initial Screening Results", "Supporting Documents Deadline",
            "AAO Pre-Application Screening", "Examination Fee Payment",
        ):
            with self.subTest(role=role):
                self.assertEqual(check(kyoto("March 11, 2027", role=role))[0],
                                 "no_explicit_deadline")

    def test_yearless_expired_and_far_future_dates_are_not_promoted(self):
        for closing in ("March 11", "March 11, 2025", "March 11, 2030", "03/04/2027"):
            with self.subTest(closing=closing):
                self.assertEqual(check(kyoto(closing))[0], "no_explicit_deadline")
        self.assertEqual(check(kyoto("March 11, 2027"), now=datetime(
            2027, 3, 12, tzinfo=UTC,
        ))[0], "no_explicit_deadline")

    def test_master_or_missing_economics_identity_does_not_borrow_doctoral_table(self):
        html = kyoto("March 11, 2027")
        for changed in (
            html.replace("Application Procedures for Doctoral Programme",
                         "Application Procedures for Master's Programme"),
            html.replace("Graduate School of Economics", "Graduate School of Medicine"),
            html.replace("East Asia Sustainable Economic Development Studies", "Statistics"),
            html.replace("Overall Schedule for Application and Selection", "Other dates"),
        ):
            with self.subTest(html=changed):
                self.assertEqual(check(changed)[0], "no_explicit_deadline")
        self.assertIsNone(check(html, url=KYOTO.replace("doctoral", "masters")))
        self.assertIsNone(check(html, url=KYOTO.replace("kyoto-u.ac.jp", "example.edu")))

    def test_conflicting_or_incomplete_application_rows_are_held(self):
        for closing in ("March 12, 2027", "March 12"):
            extra = (
                f"<tr><td>March 1 ～{closing} “Strict Deadline”</td><td>{ROLE}</td></tr>"
            )
            self.assertEqual(check(kyoto("March 11, 2027", extra=extra))[0],
                             "ambiguous_deadline")

    def test_range_endpoints_cannot_hide_other_deadlines_or_reverse_order(self):
        for opening in (
            "March 12, 2027", "March 1 or March 5", "TBA", "February 30, 2027",
        ):
            html = kyoto().replace("March 1 (9am/Mon)", opening)
            with self.subTest(opening=opening):
                self.assertEqual(check(html)[0], "no_explicit_deadline")
        for closing in (
            "March 11, 2027 or March 15, 2027", "March 11, 2027 for domestic applicants",
        ):
            with self.subTest(closing=closing):
                self.assertEqual(check(kyoto(closing))[0], "no_explicit_deadline")


if __name__ == "__main__":
    unittest.main()
