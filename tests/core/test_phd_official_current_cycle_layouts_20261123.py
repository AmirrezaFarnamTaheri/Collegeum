"""Regression tests for real-looking, institution-owned Economics PhD pages.

Every example is synthetic HTML based on a public official admissions layout.
A date cannot be attributed to the catalogue without a separate robots-aware
fetch of the university page by Collegeum's normal verifier.
"""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.update_phd_admissions import collect_official_deadline

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)
NYU = "https://www.stern.nyu.edu/programs-admissions/phd/admissions/how-to-apply"
IMPERIAL = "https://www.imperial.ac.uk/business-school/study/phd/economics/"
UMASS = "https://www.umass.edu/economics/admissions"


def stern_real_layout(*, degree: str = "PhD", economics: bool = True,
                      deadline: str = "December 15, 2026") -> str:
    programme = "Economics" if economics else "Accounting"
    return (
        f"<h1>{degree} | How to Apply</h1><h2>How To Apply</h2>"
        f"<p>Our Fall 2027 application is now open. The application "
        f"deadline is {deadline} at 11:59PM ET.</p>"
        "<h2>Application Requirements</h2>"
        "<p>All applicants to the NYU Stern School of Business PhD Program "
        "are required to submit a complete application for admission.</p>"
        "<table><tr><th>Area of Study</th><th>Preferred Test</th></tr>"
        f"<tr><td>{programme}</td><td>GRE</td></tr></table>"
    )


def imperial_real_layout(*, degree: str = "PhD",
                         programme: str = "Economics & Public Policy pathway",
                         deadline: str = "2 December 2026", extra: str = "") -> str:
    return (
        f"<h1>{programme}</h1>"
        f"<p>{degree}</p>"
        "<p>Start date: September 2027</p>"
        "<p>Duration: Five to six years</p>"
        f"<p>Next application deadline: {deadline}</p>"
        + extra
    )


def umass_real_layout(*, phd: bool = True, deadline: str = "January 10, 2027",
                      extra: str = "") -> str:
    scope = (
        "<p>All entering PhD students must have completed one semester of "
        "microeconomics and econometrics.</p>"
        "<p>Applicants interested in earning both a Masters and Ph.D. "
        "should apply directly to the Ph.D. program.</p>"
        if phd else "<p>All entering Master's students must have completed microeconomics.</p>"
    )
    return (
        "<h1>Admissions</h1>"
        "<p>Department of Economics</p>"
        f"<p>Application deadline for the program starting fall 2027: "
        f"{deadline}</p>"
        + scope
        + "<p>Application fee waiver deadline: December 1, 2026.</p>"
        + extra
    )


class ActualUniversityLayoutRegressions(unittest.TestCase):
    def test_stern_phd_breadcrumb_and_h2_how_to_apply_preserve_cutoff(self):
        self.assertEqual(
            collect_official_deadline(stern_real_layout(), now=NOW, source_url=NYU)[:2],
            ("verified", "2026-12-15"),
        )

    def test_stern_requires_phd_breadcrumb_and_economics_own_table_row(self):
        for html in (
            stern_real_layout(degree="MBA"),
            stern_real_layout(economics=False)
            + "<footer>Economics is taught here too.</footer>",
            stern_real_layout(deadline="December 15"),
        ):
            with self.subTest(html=html):
                self.assertNotEqual(
                    collect_official_deadline(html, now=NOW, source_url=NYU)[0],
                    "verified",
                )

    def test_imperial_economics_public_policy_pathway_with_phd_and_current_date(self):
        status, day, excerpt = collect_official_deadline(
            imperial_real_layout(), now=NOW, source_url=IMPERIAL,
        )
        self.assertEqual((status, day), ("verified", "2026-12-02"))
        self.assertIn("2 December 2026", excerpt)

    def test_imperial_does_not_take_masters_other_subject_or_yearless_date(self):
        for html, url in (
            (imperial_real_layout(degree="MSc"), IMPERIAL),
            (imperial_real_layout(programme="Marketing pathway"), IMPERIAL),
            (imperial_real_layout(deadline="2 December"), IMPERIAL),
            (imperial_real_layout(), "https://www.imperial.ac.uk/business-school/study/masters/economics/"),
            (imperial_real_layout(), "https://unrelated.example.edu/business-school/study/phd/economics/"),
            (imperial_real_layout(extra="<p>Scholarship deadline: 4 December 2026.</p>"), IMPERIAL),
        ):
            with self.subTest(html=html, url=url):
                result = collect_official_deadline(html, now=NOW, source_url=url)
                if "Scholarship deadline:" in html:
                    self.assertEqual(result[:2], ("verified", "2026-12-02"))
                else:
                    self.assertNotEqual(result[0], "verified")

    def test_imperial_competing_next_application_cutoffs_are_ambiguous(self):
        html = imperial_real_layout(extra=(
            "<p>Next application deadline: 10 January 2027.</p>"
        ))
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=IMPERIAL)[0],
            "ambiguous_deadline",
        )

    def test_umass_economics_phd_deadline_not_confused_with_fee_waiver(self):
        status, day, excerpt = collect_official_deadline(
            umass_real_layout(), now=NOW, source_url=UMASS,
        )
        self.assertEqual((status, day), ("verified", "2027-01-10"))
        self.assertIn("January 10, 2027", excerpt)

    def test_umass_requires_official_economics_phd_context_and_full_year_date(self):
        for html, url in (
            (umass_real_layout(phd=False), UMASS),
            (umass_real_layout(deadline="January 10"), UMASS),
            (umass_real_layout(), "https://www.umass.edu/sociology/admissions"),
            (umass_real_layout(), "https://foreign.example.edu/economics/admissions"),
        ):
            with self.subTest(html=html, url=url):
                self.assertNotEqual(
                    collect_official_deadline(html, now=NOW, source_url=url)[0],
                    "verified",
                )

    def test_umass_two_explicit_application_deadlines_cannot_be_silently_combined(self):
        html = umass_real_layout(extra=(
            "<p>Application deadline for the program starting fall 2027: "
            "January 20, 2027.</p>"
        ))
        self.assertEqual(
            collect_official_deadline(html, now=NOW, source_url=UMASS)[0],
            "ambiguous_deadline",
        )


if __name__ == "__main__":
    unittest.main()
