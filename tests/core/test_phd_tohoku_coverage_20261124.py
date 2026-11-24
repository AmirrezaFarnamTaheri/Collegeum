"""Tohoku's formal doctoral period stays separate from other routes/stages."""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.phd_admissions_tohoku import collect_deadline
from tools.update_phd_admissions import (
    DATE_PATTERN,
    PageText,
    _parse_date,
    collect_official_deadline,
)

NOW = datetime(2026, 11, 24, tzinfo=UTC)
URL = "https://www.econ.tohoku.ac.jp/en/gpem/gpem-admission"
GUIDE = (
    "https://www.econ.tohoku.ac.jp/wp/wp-content/uploads/2026/11/"
    "2.GPEM-Guideline_Doctoral_202710.pdf"
)
FORMAL = "March 1, 2027 ～ March 31, 2027, 16:00 (JST)"
PRELIM = "December 1, 2026 ～ February 15, 2027, 16:00 (JST)"


def doctoral(formal=FORMAL, prelim=PRELIM):
    return (
        "<h3>Doctoral Program</h3><table>"
        f"<tr><th>Pre application</th><td>{prelim}</td></tr>"
        "<tr><th>Online application</th>"
        "<td>Please refer to the application guidelines for details.</td></tr>"
        f"<tr><th>Application Period</th><td>{formal}</td></tr>"
        "<tr><th>Result notification</th><td>Mid May, 2027</td></tr></table>"
    )


def page(formal=FORMAL, prelim=PRELIM):
    return (
        '<h1>GPEM Admission</h1><h3>Application Guideline:</h3>'
        f'<a href="{GUIDE}">Doctoral Program</a>'
        "<h2>Application Schedule for 2027 Academic Year Foreign Student "
        "Screening (October Entrance)</h2>"
        "<h3>Master’s Program</h3><table><tr><th>Application Period</th>"
        "<td>January 15, 2027 ～ January 29, 2027, 16:00 (JST)</td></tr></table>"
        + doctoral(formal, prelim)
        + "<h3>Continuation from Master’s Program to Doctoral Program</h3>"
        "<table><tr><th>Application Period</th>"
        "<td>February 1, 2027 ～ February 28, 2027, 16:00 (JST)</td></tr></table>"
        "<p>Graduate School of Economics and Management / Faculty of Economics, "
        "Tohoku University</p>"
    )


def read(html, *, url=URL, now=NOW):
    return collect_official_deadline(html, now=now, source_url=url)


class TohokuDeadlineTests(unittest.TestCase):
    def test_formal_doctoral_cutoff_and_required_pre_application_remain_distinct(self):
        status, day, excerpt = read(page())
        self.assertEqual((status, day), ("verified", "2027-03-31"))
        self.assertIn("Doctoral Program (Foreign Student Screening)", excerpt)
        self.assertIn("Application Period ends March 31, 2027", excerpt)
        self.assertIn("required Pre application ends February 15, 2027", excerpt)
        self.assertLessEqual(len(excerpt), 180)

    def test_unknown_hosts_and_routes_are_unhandled(self):
        parser = PageText()
        parser.feed(page())
        for url in (URL.replace("econ.tohoku.ac.jp", "example.edu"), URL + "/other"):
            with self.subTest(url=url):
                self.assertIsNone(collect_deadline(
                    parser, now=NOW, source_url=url,
                    date_pattern=DATE_PATTERN, parse_date=_parse_date,
                ))

    def test_known_route_requires_safe_source_and_explicit_institutional_identity(self):
        for url in (
            URL.replace("https:", "http:"),
            URL.replace("www.econ.tohoku.ac.jp", "user@www.econ.tohoku.ac.jp"),
            URL.replace("www.econ.tohoku.ac.jp", "www.econ.tohoku.ac.jp:444"),
        ):
            with self.subTest(url=url):
                self.assertNotEqual(read(page(), url=url)[0], "verified")
        for old, new in (
            ("GPEM Admission", "Graduate Admissions"),
            ("Graduate School of Economics and Management", "School of Engineering"),
            ("Faculty of Economics", "Faculty of Science"),
            ("Tohoku University", "Other University"),
        ):
            with self.subTest(old=old):
                self.assertNotEqual(read(page().replace(old, new))[0], "verified")

    def test_linked_named_doctoral_guide_cannot_be_external_masters_or_continuation(self):
        for target in (
            GUIDE.replace("www.econ.tohoku.ac.jp", "example.edu"),
            GUIDE.replace("https:", "http:"),
            GUIDE.replace("Doctoral_", "Master_"),
            GUIDE.replace("Doctoral_", "Doctoral-Continuation_"),
            GUIDE.replace("202710.pdf", "202610.pdf"),
        ):
            with self.subTest(target=target):
                self.assertNotEqual(read(page().replace(GUIDE, target))[0], "verified")

    def test_doctoral_section_is_required_and_masters_dates_cannot_replace_it(self):
        for html in (
            page().replace(doctoral(), ""),
            page().replace("<h3>Doctoral Program</h3>", "<h3>Master’s Program</h3>"),
            page().replace("<h3>Doctoral Program</h3>", "<h3>Doctoral Program in Management</h3>"),
        ):
            self.assertNotEqual(read(html)[0], "verified")

    def test_yearless_invalid_or_qualified_formal_values_are_not_promoted(self):
        for value in (
            "March 1 ～ March 31, 2027, 16:00 (JST)",
            "March 1, 2027 ～ March 31, 16:00 (JST)",
            "March 1, 2027 ～ February 30, 2027, 16:00 (JST)",
            "April 1, 2027 ～ March 31, 2027, 16:00 (JST)",
            FORMAL + " or April 15",
            FORMAL + "; domestic applicants: TBD",
            "03/04/2027 ～ 04/05/2027",
        ):
            with self.subTest(value=value):
                self.assertNotEqual(read(page(value))[0], "verified")

    def test_required_preliminary_stage_must_be_complete_and_before_formal_period(self):
        for value in (
            "December 1, 2026 ～ February 15, 16:00 (JST)",
            "December 1 ～ February 15, 2027, 16:00 (JST)",
            "December 1, 2026 ～ April 15, 2027, 16:00 (JST)",
            PRELIM + "; other applicants: TBD",
        ):
            with self.subTest(value=value):
                self.assertNotEqual(read(page(prelim=value))[0], "verified")

    def test_missing_preliminary_or_formal_application_label_cannot_be_inferred(self):
        for label in ("Pre application", "Application Period"):
            with self.subTest(label=label):
                html = page().replace(f"<th>{label}</th>", "<th>Eligibility</th>")
                self.assertNotEqual(read(html)[0], "verified")

    def test_current_intake_heading_is_required_without_borrowing_its_year(self):
        for html in (
            page().replace("for 2027 Academic Year", "for Academic Year"),
            page().replace("Foreign Student Screening", "Domestic Student Screening"),
            page().replace("for 2027 Academic Year", "for 2026 Academic Year"),
        ):
            self.assertNotEqual(read(html)[0], "verified")

    def test_repeated_doctoral_sections_cannot_hide_unknown_or_conflicting_dates(self):
        for other in (
            doctoral("March 1, 2027 ～ April 1, 2027, 16:00 (JST)"),
            doctoral("March 1, 2027 ～ March 31"),
            doctoral(prelim="December 1, 2026 ～ February 16, 2027, 16:00 (JST)"),
        ):
            with self.subTest(other=other):
                html = page().replace(
                    "<h3>Continuation from Master’s", other + "<h3>Continuation from Master’s",
                )
                self.assertEqual(read(html), ("ambiguous_deadline", None, None))

    def test_repeated_schedule_and_nested_applicant_heading_cannot_hide_conflict(self):
        duplicate = (
            "<h2>Application Schedule for 2027 Academic Year Foreign Student "
            "Screening (October Entrance)</h2>"
            + doctoral("March 1, 2027 ～ April 1, 2027, 16:00 (JST)")
        )
        self.assertEqual(read(page() + duplicate), ("ambiguous_deadline", None, None))
        html = page().replace(
            "<h3>Doctoral Program</h3>",
            "<h3>Doctoral Program</h3><h4>International applicants only</h4>",
        )
        self.assertNotEqual(read(html)[0], "verified")

    def test_partial_duplicate_period_or_added_applicant_column_fails_closed(self):
        for extra in (
            "<tr><th>Application Period</th><td>March 1, 2027 ～ March 31</td></tr>",
            "<tr><th>Application Period</th><td></td></tr>",
            "<tr><th>Application Period for domestic students</th><td>TBD</td></tr>",
        ):
            html = page().replace(doctoral(), doctoral().replace("</table>", extra + "</table>"))
            self.assertNotEqual(read(html)[0], "verified")
        html = page().replace(
            f"<td>{FORMAL}</td>", f"<td>{FORMAL}</td><td>International applicants</td>",
        )
        self.assertNotEqual(read(html)[0], "verified")

    def test_formal_deadline_does_not_change_after_pre_application_closes(self):
        result = read(page(), now=datetime(2027, 2, 16, tzinfo=UTC))
        self.assertEqual(result[:2], ("verified", "2027-03-31"))
        self.assertIn("required Pre application ends February 15, 2027", result[2])

    def test_expired_formal_deadline_or_intake_is_not_current(self):
        for now in (datetime(2027, 4, 1, tzinfo=UTC), datetime(2027, 10, 2, tzinfo=UTC)):
            with self.subTest(now=now):
                self.assertEqual(read(page(), now=now), ("no_explicit_deadline", None, None))


if __name__ == "__main__":
    unittest.main()
