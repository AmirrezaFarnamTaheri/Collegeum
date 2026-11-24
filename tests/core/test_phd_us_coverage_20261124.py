"""Programme and deadline-role regressions for reviewed US university layouts.

Small synthetic documents preserve the relevant HTML relationships without
embedding university pages. Only independent robots-aware checks may publish
observations; these tests do not write the live catalogue.
"""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.phd_admissions_us import collect_deadline
from tools.update_phd_admissions import (
    DATE_PATTERN,
    PageText,
    _parse_date,
    collect_official_deadline,
)

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
CMU = "https://www.cmu.edu/tepper/programs/phd/admissions"
NOTRE_DAME = "https://economics.nd.edu/graduate/admissions-and-funding/"
WASHU = "https://gradstudies.artsci.washu.edu/browse/economics"
PENN = (
    "https://economics.sas.upenn.edu/graduate/prospective-students/application-guidelines"
)


def parse(html: str, url: str):
    page = PageText()
    page.feed(html)
    return collect_deadline(
        page, now=NOW, source_url=url, date_pattern=DATE_PATTERN, parse_date=_parse_date,
    )


def cmu(day="December 15, 2026", extra=""):
    return (
        "<h1>Ph.D. Admissions</h1>"
        '<a href="/tepper/programs/phd/economics">Economics</a>'
        "<p>Learn how to apply to the Ph.D. program at the Tepper School of Business.</p>"
        "<h2>Application Instructions</h2><h3>Online Application Components</h3>"
        f"<p>The application site will remain open until {day}.</p>"
        f"{extra}<h2>Contact the Ph.D. Program</h2>"
    )


def notre_dame(day="January 15th, 2027", extra=""):
    return (
        "<p>Department of Economics</p><h1>Admissions and Funding</h1>"
        f"<p>Deadline: {day}</p>{extra}"
        "<h2>Application requirements</h2>"
        "<p>These materials are required for application to the Ph.D. program:</p>"
        "<h2>Timeline</h2><p>Dates based on previous years</p>"
        "<p>Deadline: January 20, 2027</p>"
        "<h2>Tuition</h2><p>Stipend funding for 2026-27.</p>"
    )


def washu(day="December 1, 2026", extra=""):
    return (
        "<h1>Economics</h1><h2>Economics</h2>"
        "<p>The doctoral program prepares PhD students for research.</p>"
        "<h4>Application deadline:</h4>"
        f"<h4>PhD - {day} at 11:59 PM Eastern Standard Time</h4>{extra}"
        "<h4>MA - February 15, 2027 at 11:59 PM Eastern Standard Time</h4>"
        "<h3>See also</h3>"
    )


def penn(day="December 8, 2026", extra=""):
    return (
        "<p>Department of Economics</p><h1>Application Guidelines</h1>"
        f"<p>The deadline to submit your application is {day}.</p>{extra}"
        "<h2>Application Deadlines</h2>"
        "<p>Applicants seeking a fellowship must submit an application by December 8, 2026.</p>"
        "<h2>International Applicants</h2>"
        "<p>Admissions Information to the Ph.D. Program in Economics</p>"
    )


class ReviewedUsOfficialLayoutsTests(unittest.TestCase):
    def test_current_dates_in_reviewed_programme_layouts(self):
        cases = (
            (cmu(), CMU, "2026-12-15"),
            (notre_dame(), NOTRE_DAME, "2027-01-15"),
            (washu(), WASHU, "2026-12-01"),
            (penn(), PENN, "2026-12-08"),
        )
        for html, url, expected in cases:
            with self.subTest(url=url):
                status, day, excerpt = parse(html, url)
                self.assertEqual((status, day), ("verified", expected))
                self.assertIn("Economics", excerpt)
                self.assertLessEqual(len(excerpt), 180)

    def test_yearless_expired_invalid_and_ambiguous_numeric_dates_fail_closed(self):
        for template, url in (
            (cmu, CMU), (notre_dame, NOTRE_DAME), (washu, WASHU), (penn, PENN),
        ):
            for invalid in ("December 15", "December 15, 2025", "February 30, 2027", "12/3/2026"):
                with self.subTest(url=url, invalid=invalid):
                    result = parse(template(invalid), url)
                    self.assertNotEqual(result[0], "verified")
                    self.assertIsNone(result[1])

    def test_conflicting_current_application_dates_are_ambiguous(self):
        cases = (
            (
                cmu(extra="<p>The application site will remain open until December 18, 2026.</p>"),
                CMU,
            ),
            (notre_dame(extra="<p>Deadline: January 18, 2027</p>"), NOTRE_DAME),
            (washu(extra="<h4>PhD - December 18, 2026</h4>"), WASHU),
            (
                penn(extra="<p>The deadline to submit your application is December 18, 2026.</p>"),
                PENN,
            ),
        )
        for html, url in cases:
            with self.subTest(url=url):
                self.assertEqual(parse(html, url), ("ambiguous_deadline", None, None))

    def test_partial_applicant_dates_do_not_silently_become_universal(self):
        html = washu(extra="<h4>PhD - January 20</h4>")
        self.assertEqual(parse(html, WASHU), ("ambiguous_deadline", None, None))

    def test_single_role_with_alternate_or_incomplete_dates_is_ambiguous(self):
        for template, url in (
            (cmu, CMU), (notre_dame, NOTRE_DAME), (washu, WASHU), (penn, PENN),
        ):
            for suffix in (
                " or January 5, 2027",
                " for international applicants; February 1, 2027 for domestic applicants",
                " for international applicants; domestic applicants: January 5",
                ". Domestic applicants: January 5",
                ". International applicants: TBD",
                ". A later application deadline will be announced",
                " - January 5",
                " / 01/05/2027",
            ):
                with self.subTest(url=url, suffix=suffix):
                    result = collect_official_deadline(
                        template("December 15, 2026" + suffix), now=NOW, source_url=url,
                    )
                    self.assertEqual(result, ("ambiguous_deadline", None, None))

    def test_harmless_time_and_trailing_sentences_preserve_current_deadline(self):
        examples = (
            (cmu("December 15, 2026. Please submit all materials online"), CMU,
             "2026-12-15"),
            (notre_dame("January 15, 2027 at 11:59 p.m. EST. Apply using the portal"),
             NOTRE_DAME, "2027-01-15"),
            (washu().replace(
                "December 1, 2026 at 11:59 PM Eastern Standard Time</h4>",
                "December 1, 2026 at 11:59 PM Eastern Standard Time. "
                "International applicants should provide English proficiency scores.</h4>",
            ), WASHU, "2026-12-01"),
            (penn("December 8, 2026 at 5 p.m. Please submit a complete application"),
             PENN, "2026-12-08"),
        )
        for html, url, expected in examples:
            with self.subTest(url=url):
                result = collect_official_deadline(html, now=NOW, source_url=url)
                self.assertEqual(result[:2], ("verified", expected))

    def test_cmu_requires_explicit_economics_doctoral_route_and_shared_scope(self):
        variants = (
            cmu().replace('/phd/economics">Economics', '/phd/finance">Finance'),
            cmu().replace('href="/tepper/', 'href="https://other.example/tepper/'),
            cmu().replace("Ph.D. program at the Tepper", "MBA program at the Tepper"),
            cmu().replace("Application Instructions", "Workshop Registration"),
        )
        for html in variants:
            with self.subTest(html=html):
                self.assertNotEqual(parse(html, CMU)[0], "verified")

    def test_notre_dame_history_and_non_doctoral_requirements_do_not_qualify(self):
        html = notre_dame().replace("<p>Deadline: January 15th, 2027</p>", "")
        self.assertNotEqual(parse(html, NOTRE_DAME)[0], "verified")
        html = notre_dame().replace(
            "application to the Ph.D. program", "application to the MA program",
        )
        self.assertNotEqual(parse(html, NOTRE_DAME)[0], "verified")

    def test_washu_masters_and_other_subjects_do_not_supply_economics_phd_date(self):
        for html in (
            washu().replace("PhD - December 1, 2026", "MA - December 1, 2026"),
            washu().replace("<h1>Economics</h1>", "<h1>Political Science</h1>"),
            washu().replace("Application deadline:", "Supporting document deadline:"),
            washu().replace(
                "doctoral program prepares PhD students", "master's program prepares MA students",
            ),
        ):
            with self.subTest(html=html):
                self.assertNotEqual(parse(html, WASHU)[0], "verified")

    def test_penn_needs_general_submission_cutoff_not_only_fellowship_date(self):
        html = penn().replace(
            "<p>The deadline to submit your application is December 8, 2026.</p>", "",
        )
        self.assertNotEqual(parse(html, PENN)[0], "verified")
        html = penn().replace("Ph.D. Program in Economics", "Master's Program in Economics")
        self.assertNotEqual(parse(html, PENN)[0], "verified")

    def test_washu_later_programme_heading_cannot_supply_missing_phd_deadline(self):
        html = washu().replace(
            "<h4>PhD - December 1, 2026 at 11:59 PM Eastern Standard Time</h4>",
            "<h4>Psychology</h4><h4>PhD - December 15, 2026</h4>",
        )
        self.assertNotEqual(parse(html, WASHU)[0], "verified")

    def test_date_is_not_borrowed_from_neighboring_event_in_same_paragraph(self):
        for template, url in (
            (cmu, CMU), (notre_dame, NOTRE_DAME), (washu, WASHU), (penn, PENN),
        ):
            html = template("December 15. Course begins January 15, 2027")
            with self.subTest(url=url):
                self.assertNotEqual(parse(html, url)[0], "verified")

    def test_unhandled_official_paths_and_unrelated_hosts_return_none(self):
        for url in (
            "https://not-cmu.example/tepper/programs/phd/admissions",
            "https://www.cmu.edu/tepper/programs/mba/admissions",
            "https://gradschool.princeton.edu/admission-onboarding/prepare/application-deadlines",
        ):
            with self.subTest(url=url):
                self.assertIsNone(parse(cmu(), url))

    def test_insecure_supported_route_cannot_return_a_verified_date(self):
        self.assertNotEqual(parse(cmu(), CMU.replace("https:", "http:"))[0], "verified")


if __name__ == "__main__":
    unittest.main()
