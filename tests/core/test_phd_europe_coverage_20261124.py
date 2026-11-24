"""European official layouts: programme scope, date role, and fail-closed cases.

Small synthetic documents reproduce observed structures without storing full
university pages.  Network fetching remains the existing verifier's concern.
"""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.phd_admissions_europe import collect_deadline
from tools.update_phd_admissions import (
    DATE_PATTERN,
    PageText,
    _parse_date,
    collect_official_deadline,
)

NOW = datetime(2026, 11, 24, tzinfo=UTC)
CEU = "https://www.ceu.edu/admissions/doctoral"
DIW = "https://www.diw.de/en/diw_01.c.799242.en/application.html"
NHH = "https://www.nhh.no/en/study-programmes/phd-programme-at-nhh/vacant-phd-positions/"
COLOGNE = "https://cgs.uni-koeln.de/en/economics/phd-programme/application"
EDINBURGH = "https://study.ed.ac.uk/programmes/postgraduate-research/278-economics"
TRINITY = (
    "https://www.tcd.ie/economics/programmes/postgraduate/"
    "phd-in-economics-/admission-requirements/"
)


def read(html, url):
    return collect_official_deadline(html, now=NOW, source_url=url)


def read_adapter(html, url):
    parser = PageText()
    parser.feed(html)
    return collect_deadline(
        parser, now=NOW, source_url=url,
        date_pattern=DATE_PATTERN, parse_date=_parse_date,
    )


def ceu(deadline="January 15, 2027"):
    return (
        "<h1>Apply to a Doctoral Program at CEU</h1>"
        '<a href="https://www.ceu.edu/academics/degrees/phd-economics#requirements">'
        "Economics</a><h2>Doctoral Degree at CEU - Application Deadlines</h2>"
        f"<ul><li>Deadline: {deadline}</li><li>Applicable to: all applicants</li></ul>"
        "<h2>After Admission</h2><p>Deadline: August 1, 2027</p>"
    )


def diw(deadline="15 January 2027"):
    return (
        "<h1>Application</h1><h2>Application Schedule</h2>"
        "<p>Start of application period: 15 October 2026</p>"
        f"<p>Deadline for applications: {deadline}</p>"
        "<h2>Programme</h2><p>DIW Graduate Center offers a five-year program "
        "of in-depth training in economics. After completion you obtain a PhD "
        "from one of Berlin’s universities.</p>"
        "<h2>References</h2><p>Deadline for applications: 22 January 2027</p>"
    )


def nhh(deadline="15 January 2027"):
    return (
        "<h1>Vacant PhD positions</h1>"
        "<p>NHH is seeking applicants for our PhD Programme.</p>"
        "<p>The main application deadline is normally 15 January/September, "
        f"our next deadline is {deadline}.</p>"
        "<p>PhD Research Scholar positions - Department of Economics</p>"
        "<p>PhD Research Scholar positions - Department of Finance</p>"
    )


def cologne(deadline="March 15th, 2027"):
    return (
        "<h2>Application to the PhD Programme in Economics</h2>"
        "<p>Applications for the MSc Stage are open until March 31st, 2027.</p>"
        "<p>Applications for admission to the PhD Stage for the academic year "
        "starting October 2027 are open from 15th December, 2026 "
        f"until {deadline} 23:59 CET.</p>"
    )


def edinburgh(deadline="1 August 2027"):
    return (
        "<h1>Economics PhD with Integrated Study</h1>"
        "<h2>When to apply</h2><table><tr><th>Programme start date</th>"
        "<th>Application deadline</th></tr><tr><td>1 October 2027</td>"
        f"<td>{deadline}</td></tr></table>"
        "<p>Funding consideration deadline: 15 January 2027</p>"
    )


def trinity(deadline="31 March 2027"):
    return (
        "<h1>Admission Requirements &amp; How to Apply</h1>"
        "<h2>PhD in Economics: Requirements</h2><p>Research proposal required.</p>"
        "<h2>Application Deadlines</h2>"
        f"<p>Deadline for PhD applications : {deadline} "
        "Deadline for funding consideration : 17 January 2027</p>"
        "<h2>Fees</h2><p>Fee payment deadline: 15 April 2027</p>"
    )


CASES = (
    (ceu, CEU, "2027-01-15", "January 15, 2027"),
    (diw, DIW, "2027-01-15", "15 January 2027"),
    (nhh, NHH, "2027-01-15", "15 January 2027"),
    (cologne, COLOGNE, "2027-03-15", "March 15th, 2027"),
    (edinburgh, EDINBURGH, "2027-08-01", "1 August 2027"),
    (trinity, TRINITY, "2027-03-31", "31 March 2027"),
)


class EuropeanOfficialDeadlineTests(unittest.TestCase):
    def test_reviewed_layouts_extract_only_the_application_cutoff(self):
        for fixture, url, expected, printed in CASES:
            with self.subTest(url=url):
                status, day, excerpt = read(fixture(), url)
                self.assertEqual((status, day), ("verified", expected))
                self.assertIn(printed, excerpt)
                self.assertLessEqual(len(excerpt), 180)

    def test_yearless_and_stale_dates_remain_unconfirmed(self):
        for fixture, url, _, _ in CASES:
            for date_text in ("January 15", "January 15, 2025", "03/04/2027"):
                with self.subTest(url=url, date=date_text):
                    result = read(fixture(date_text), url)
                    self.assertEqual(result, ("no_explicit_deadline", None, None))

    def test_other_sites_and_insecure_sources_are_unhandled(self):
        for fixture, url, _, _ in CASES:
            with self.subTest(url=url):
                self.assertIsNone(read_adapter(fixture(), "https://example.edu/"))
                self.assertIsNone(read_adapter(fixture(), url.replace("https://", "http://")))

    def test_ceu_needs_doctoral_economics_route_and_universal_applicability(self):
        for html in (
            ceu().replace("phd-economics", "ma-economics"),
            ceu().replace("https://www.ceu.edu/academics", "https://example.edu/academics"),
            ceu().replace("Applicable to: all applicants", "Applicable to: domestic applicants"),
            ceu().replace("Doctoral Program at CEU", "Masters Program at CEU"),
        ):
            self.assertEqual(read(html, CEU)[0], "no_explicit_deadline")

    def test_ceu_conflicting_application_dates_are_ambiguous(self):
        html = ceu().replace(
            "<li>Applicable to:", "<li>Deadline: January 16, 2027</li><li>Applicable to:",
        )
        self.assertEqual(read(html, CEU)[0], "ambiguous_deadline")

    def test_ceu_qualified_ancillary_deadline_is_not_an_application_field(self):
        for qualifier in ("Funding", "Document", "Payment", "Scholarship", "Reference"):
            with self.subTest(qualifier=qualifier):
                html = ceu().replace("<li>Deadline:", f"<li>{qualifier} deadline:")
                self.assertEqual(read(html, CEU), ("no_explicit_deadline", None, None))

    def test_other_qualified_application_labels_do_not_become_generic_cutoffs(self):
        for html, url in (
            (diw().replace(
                "Deadline for applications:", "Funding deadline for applications:",
            ), DIW),
            (trinity().replace(
                "Deadline for PhD applications :", "Funding deadline for PhD applications :",
            ), TRINITY),
        ):
            with self.subTest(url=url):
                self.assertEqual(read(html, url), ("no_explicit_deadline", None, None))

    def test_repeated_application_labels_cannot_discard_incomplete_dates(self):
        for date_text in ("January 16", "February 30, 2027", "03/04/2027", "TBA"):
            cases = (
                (ceu().replace(
                    "<li>Applicable to:",
                    f"<li>Deadline: {date_text}</li><li>Applicable to:",
                ), CEU),
                (diw().replace(
                    "<h2>Programme</h2>",
                    f"<p>Deadline for applications: {date_text}</p><h2>Programme</h2>",
                ), DIW),
                (trinity().replace(
                    "<h2>Fees</h2>",
                    f"<p>Deadline for PhD applications: {date_text}</p><h2>Fees</h2>",
                ), TRINITY),
                (nhh() + (
                    "<p>The main application deadline is normally in January, "
                    f"our next deadline is {date_text}.</p>"
                ), NHH),
                (cologne() + (
                    "<p>Applications for admission to the PhD Stage are open "
                    f"until {date_text}.</p>"
                ), COLOGNE),
            )
            for html, url in cases:
                with self.subTest(url=url, date=date_text):
                    self.assertEqual(read(html, url), ("ambiguous_deadline", None, None))

    def test_second_label_in_the_same_block_remains_relevant(self):
        cases = (
            (ceu("January 15, 2027; Deadline: January 16"), CEU),
            (diw("15 January 2027; Deadline for applications: 16 January"), DIW),
            (trinity("31 March 2027; Deadline for PhD applications: 1 April"), TRINITY),
        )
        for html, url in cases:
            with self.subTest(url=url):
                self.assertEqual(read(html, url), ("ambiguous_deadline", None, None))

    def test_scalar_application_value_cannot_hide_alternative_dates(self):
        for fixture, url, _, printed in CASES:
            for suffix in (" or 16 January", " or 16 January 2027", ", 16 January 2027"):
                with self.subTest(url=url, suffix=suffix):
                    self.assertNotEqual(read(fixture(printed + suffix), url)[0], "verified")

    def test_scalar_values_reject_unknown_applicant_restrictions_or_partial_cutoffs(self):
        suffixes = (
            " for international applicants; domestic applicants: 5 February",
            ". Domestic applicants: TBD.",
            " (international only)",
            " Deadline: January 16",
            " Deadline for applications: January 16",
            " Deadline for PhD applications: January 16",
        )
        for fixture, url, _, printed in CASES:
            for suffix in suffixes:
                with self.subTest(url=url, suffix=suffix):
                    self.assertNotEqual(read(fixture(printed + suffix), url)[0], "verified")

    def test_scalar_values_preserve_observed_clock_and_timezone_suffixes(self):
        cases = (
            (ceu("January 15, 2027 (23:59, Central European Time)"), CEU, "2027-01-15"),
            (diw("15 January 2027, 23:59 CET."), DIW, "2027-01-15"),
            (nhh("15 January 2027"), NHH, "2027-01-15"),
            (cologne("March 15th, 2027"), COLOGNE, "2027-03-15"),
        )
        for html, url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(read(html, url)[:2], ("verified", expected))

    def test_repeated_and_nested_named_sections_cannot_hide_other_cutoffs(self):
        cases = (
            (ceu(), CEU, "Doctoral Degree at CEU - Application Deadlines",
             "<li>Deadline: January 16, 2027</li><li>Applicable to: all applicants</li>"),
            (diw(), DIW, "Application Schedule",
             "<p>Deadline for applications: 16 January 2027</p>"),
            (trinity(), TRINITY, "Application Deadlines",
             "<p>Deadline for PhD applications: 1 April 2027</p>"),
        )
        for html, url, title, content in cases:
            for tag in ("h2", "h3", "h4"):
                with self.subTest(url=url, tag=tag):
                    second_section = f"<{tag}>{title}</{tag}>{content}"
                    self.assertEqual(
                        read(html + second_section, url),
                        ("ambiguous_deadline", None, None),
                    )

    def test_matching_nested_heading_does_not_hide_later_parent_content(self):
        html = ceu().replace(
            "<li>Applicable to: all applicants</li></ul>",
            "<li>Applicable to: all applicants</li></ul>"
            "<h3>Doctoral Degree at CEU - Application Deadlines</h3>"
            "<p>Deadline: January 15, 2027</p><p>Applicable to: all applicants</p>"
            "<h3>Second application round</h3><p>Deadline: January 16, 2027</p>",
        )
        self.assertEqual(read(html, CEU), ("ambiguous_deadline", None, None))

    def test_diw_requires_explicit_economics_and_doctoral_identity(self):
        for old, new in (("training in economics", "training in statistics"),
                         ("obtain a PhD", "obtain a certificate")):
            self.assertEqual(read(diw().replace(old, new), DIW)[0], "no_explicit_deadline")

    def test_diw_does_not_borrow_a_date_from_the_following_section(self):
        html = diw().replace("<p>Deadline for applications: 15 January 2027</p>", "")
        self.assertEqual(read(html, DIW)[0], "no_explicit_deadline")

    def test_nhh_requires_economics_among_the_active_phd_positions(self):
        html = nhh().replace("Department of Economics", "Department of Accounting")
        self.assertEqual(read(html, NHH)[0], "no_explicit_deadline")

    def test_nhh_repeated_different_next_deadlines_are_ambiguous(self):
        html = nhh() + (
            "<p>The main application deadline is normally in January, "
            "our next deadline is 20 January 2027.</p>"
        )
        self.assertEqual(read(html, NHH)[0], "ambiguous_deadline")

    def test_cologne_does_not_use_masters_or_other_subject_deadline(self):
        for html in (
            cologne().replace("Applications for admission to the PhD Stage", "MSc admissions"),
            cologne().replace("PhD Programme in Economics", "PhD Programme in Finance"),
        ):
            self.assertEqual(read(html, COLOGNE)[0], "no_explicit_deadline")

    def test_cologne_competing_direct_phd_cutoffs_are_ambiguous(self):
        html = cologne() + (
            "<p>Applications for admission to the PhD Stage are open "
            "until March 20th, 2027.</p>"
        )
        self.assertEqual(read(html, COLOGNE)[0], "ambiguous_deadline")

    def test_edinburgh_keeps_the_date_in_its_labelled_column(self):
        html = edinburgh().replace(
            "<th>Application deadline</th>", "<th>Document deadline</th>",
        )
        self.assertEqual(read(html, EDINBURGH)[0], "no_explicit_deadline")

    def test_edinburgh_rejects_unrelated_degree_and_conflicting_intakes(self):
        self.assertEqual(read(
            edinburgh().replace("Economics PhD with Integrated Study", "Economics MSc"),
            EDINBURGH,
        )[0], "no_explicit_deadline")
        html = edinburgh().replace(
            "</table>", "<tr><td>1 November 2027</td><td>1 September 2027</td></tr></table>",
        )
        self.assertEqual(read(html, EDINBURGH)[0], "ambiguous_deadline")

    def test_edinburgh_does_not_discard_malformed_current_application_rows(self):
        rows = (
            "<td>1 November 2027</td><td>1 September</td>",
            "<td>1 November 2027</td><td>30 February 2027</td>",
            "<td>1 November 2027</td><td>1 December 2027</td>",
            "<td>1 November 2027</td><td></td>",
            "<td>1 November</td><td>1 September 2027</td>",
            "<td>1 November 2027</td><td>1 September 2027</td><td>International</td>",
        )
        for row in rows:
            with self.subTest(row=row):
                html = edinburgh().replace("</table>", f"<tr>{row}</tr></table>")
                self.assertEqual(read(html, EDINBURGH), ("ambiguous_deadline", None, None))

    def test_edinburgh_ignores_expired_intake_with_yearless_cutoff(self):
        html = edinburgh().replace(
            "</table>", "<tr><td>1 November 2025</td><td>1 September</td></tr></table>",
        )
        self.assertEqual(read(html, EDINBURGH)[:2], ("verified", "2027-08-01"))

    def test_trinity_yearless_application_does_not_borrow_funding_year(self):
        self.assertEqual(read(trinity("31 March"), TRINITY)[0], "no_explicit_deadline")

    def test_missing_irrelevant_funding_date_does_not_invalidate_application(self):
        for funding in ("17 January", "TBA", "February 30, 2027"):
            with self.subTest(funding=funding):
                html = trinity().replace("17 January 2027", funding)
                self.assertEqual(read(html, TRINITY)[:2], ("verified", "2027-03-31"))

    def test_trinity_requires_economics_doctoral_requirements(self):
        html = trinity().replace("PhD in Economics: Requirements", "MSc in Economics")
        self.assertEqual(read(html, TRINITY)[0], "no_explicit_deadline")


if __name__ == "__main__":
    unittest.main()
