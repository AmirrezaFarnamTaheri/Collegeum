"""Live-observed official layouts; no inferred years or applicant group choice."""
from __future__ import annotations

import unittest
from datetime import UTC, datetime

from tools.update_phd_admissions import DATE_PATTERN, _parse_date, collect_official_deadline

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
MCMASTER = "https://applygrad.mcmaster.ca/portal/start_your_app?cmd=get_results&selectedterm=sept"
KEIO = "https://www.keio.ac.jp/en/admissions/grad/doctoral/gsecon/"
MONTREAL = "https://admission.umontreal.ca/programmes/doctorat-en-sciences-economiques/"
HKUST = "https://prog-crs.hkust.edu.hk/pgprog/2027-28/mphil-phd-econ"
YORK = "https://futurestudents.yorku.ca/graduate/programs/economics"


def table(rows):
    return "<table>" + "".join(
        "<tr>" + "".join("<td>" + value + "</td>" for value in row) + "</tr>"
        for row in rows
    ) + "</table>"


def mcmaster(domestic="01/31/2027", international="01/31/2027", degree="PhD"):
    return table([
        ["Program Open for Application"],
        ["Program", "Open Date", "Domestic Close Date", "International Close Date", "Website"],
        ["Economics MA", "Apply Now", "11/15/2026", "02/28/2027", "02/28/2027", "Learn More"],
        ["Economics " + degree, "Apply Now", "11/15/2026", domestic, international, "Learn More"],
    ])


def hkust(local="1 Dec 2026", international="1 Dec 2026"):
    return (
        "<p>Doctor of Philosophy in Economics</p>"
        "<p>Offering Unit Department of Economics</p>"
        "<h2>Application Deadlines</h2>"
        "<p>For Hong Kong PhD Fellowship (HKPFS) Application: "
        "Step 1 deadline at RGC: 25 Nov 2026</p>"
        "<p>For 2027/28 Fall Term Intake (commencing in Sep 2027): "
        f"Non-local Applicants* Full-time: {international} Part-time: {international}^ "
        f"Local Applicants Full-time: {local} Part-time: {local} "
        "MPhil program is only available via the Integrated MPhil-PhD program study scheme, "
        "and is not open for individual application. Applicants should apply for the PhD program "
        "in the Online Admission System.</p>"
    )


def keio(*periods):
    return (
        "<h1>General Admissions for Doctoral Program (Graduate School of Economics)</h1>"
        + table([
            ["Application Period", *[f"Period {index}" for index in range(len(periods))]],
            ["Online Registration", *periods],
        ])
    )


def montreal(*ranges):
    return "<h1>Doctorat en sciences économiques</h1>" + "".join(
        "<div>Dates limites Déposer la demande d'admission " + period + "</div>"
        for period in ranges
    )


def york(domestic="2027-01-15", international="2027-01-15", extra=""):
    return (
        "<h1>Economics</h1><div>PhD Program Component(s) Dissertation "
        f"Deadline - Fall (Domestic Applicants Only) {domestic} "
        + extra
        + f"Deadline - Fall (International Applicants Only) {international} "
        "English Proficiency Requirement</div>"
    )


class InternationalCoverageTests(unittest.TestCase):
    def check(self, html, url):
        return collect_official_deadline(html, now=NOW, source_url=url)

    def test_mcmaster_exact_economics_phd_row_and_both_groups(self):
        status, day, excerpt = self.check(mcmaster(), MCMASTER)
        self.assertEqual((status, day), ("verified", "2027-01-31"))
        self.assertIn("Domestic Close Date: 01/31/2027", excerpt)
        self.assertIn("International Close Date: 01/31/2027", excerpt)

    def test_mcmaster_missing_conflicting_or_ambiguous_dates_do_not_verify(self):
        for html in (
            mcmaster(international="02/28/2027"),
            mcmaster(international=""),
            mcmaster(domestic="01/03/2027", international="01/03/2027"),
            mcmaster(degree="MA"),
            mcmaster().replace("11/15/2026", "11/15/2027"),
        ):
            with self.subTest(html=html):
                self.assertNotEqual(self.check(html, MCMASTER)[0], "verified")

    def test_mcmaster_does_not_skip_a_reversed_application_window(self):
        html = mcmaster().replace(
            "</table>",
            "<tr><td>Economics PhD</td><td>03/15/2027</td><td>02/28/2027</td>"
            "<td>02/28/2027</td><td>Learn More</td></tr></table>",
        )
        self.assertNotEqual(self.check(html, MCMASTER)[0], "verified")

    def test_keio_online_registration_not_paper_or_decision_cutoff(self):
        html = (
            "<h1>General Admissions for Doctoral Program (Graduate School of Economics)</h1>"
            + table([
                ["Application Period", "Application Period - Ⅰ", "Application Period - Ⅱ"],
                ["Online Registration",
                 "10:00 a.m. on May 7 (Thu) - 3:00 p.m. on May 15 (Fri), 2026",
                 "10:00 a.m. on December 14 (Mon) - 3:00 p.m. on December 24 (Thu), 2026"],
                ["Paper and Summary Submission Deadline",
                 "May 15 (Fri), 2026", "January 7 (Thu), 2027"],
                ["Announcement of Final Results", "July 10 (Fri), 2026", "February 26 (Fri), 2027"],
            ])
        )
        self.assertEqual(self.check(html, KEIO)[:2], ("verified", "2026-12-24"))
        for old, new in (
            ("Online Registration", "Payment of the Application Fee"),
            ("December 24 (Thu), 2026", "December 24"),
            ("Doctoral Program (", "Master's Program ("),
        ):
            self.assertNotEqual(self.check(html.replace(old, new), KEIO)[0], "verified")

    def test_keio_checks_every_application_period_and_the_complete_closing_field(self):
        current = "10:00 a.m. on December 14 (Mon) - 3:00 p.m. on December 24 (Thu), 2026"
        for second in (
            "10:00 a.m. on January 14 - 3:00 p.m. on January 24",
            "January 14, 2027 - January 24, 2027",
            "January 14, 2027 - 03/04/2027",
            "January 14, 2027 - January 24, 2027 or January 25, 2027",
            "December 28, 2026 - December 24, 2026",
        ):
            with self.subTest(period=second):
                self.assertNotEqual(self.check(keio(current, second), KEIO)[0], "verified")
        for value in (
            "December 14, 2026 - December 24, 2026; "
            "alternate application deadline December 30, 2026",
            "December 14 or December 15 - December 24, 2026",
            "December 14 - December 24, 2026 - December 30, 2026",
        ):
            with self.subTest(period=value):
                self.assertNotEqual(self.check(keio(value), KEIO)[0], "verified")

    def test_keio_may_ignore_only_a_complete_expired_period(self):
        html = keio("May 7 (Thu) - May 15 (Fri), 2026", "December 14 - December 24, 2026")
        self.assertEqual(self.check(html, KEIO)[:2], ("verified", "2026-12-24"))

    def test_keio_does_not_skip_an_incomplete_second_application_table(self):
        html = keio("December 14 - December 24, 2026") + table([
            ["Application Period", "Period 2"],
            ["Payment of the Application Fee", "January 24, 2027"],
        ])
        self.assertNotEqual(self.check(html, KEIO)[0], "verified")

    def test_montreal_french_full_year_closing_not_opening(self):
        html = (
            "<h1>Doctorat en sciences économiques</h1><div>Dates limites "
            "Déposer la demande d'admission Du 1<sup>er</sup> août 2026 "
            "au 1<sup>er</sup> février 2027</div>"
        )
        status, day, excerpt = self.check(html, MONTREAL)
        self.assertEqual((status, day), ("verified", "2027-02-01"))
        self.assertIn("1 er février 2027", excerpt)
        for changed in (
            html.replace("février 2027", "février"),
            html.replace("Doctorat", "Maîtrise"),
            html.replace("2026", "2025").replace("2027", "2026"),
        ):
            self.assertNotEqual(self.check(changed, MONTREAL)[0], "verified")

    def test_montreal_checks_every_labelled_range_and_rejects_additional_cutoffs(self):
        current = "Du 1 août 2026 au 1 février 2027"
        for second in (
            "Du 1 octobre 2026 au 1 mars",
            "Du 1 octobre au 1 mars 2027",
            "Du 1 octobre 2026 au 31 février 2027",
            "Du 1 octobre 2026 au 1 mars 2027",
            "Du 1 mars 2027 au 1 février 2027",
            "À annoncer",
        ):
            with self.subTest(period=second):
                self.assertNotEqual(self.check(montreal(current, second), MONTREAL)[0],
                                    "verified")
        html = montreal(current + " ou 1 mars 2027")
        self.assertNotEqual(self.check(html, MONTREAL)[0], "verified")

    def test_montreal_preserves_the_observed_card_boundary_and_expired_periods(self):
        html = montreal("Du 1 août 2025 au 1 février 2026", "Du 1 août 2026 au 1 février 2027")
        self.assertEqual(self.check(html, MONTREAL)[:2], ("verified", "2027-02-01"))
        html = montreal("Du 1 août 2026 au 1 février 2027 Offert au campus Montréal")
        self.assertEqual(self.check(html, MONTREAL)[:2], ("verified", "2027-02-01"))

    def test_hkust_applicant_groups_not_fellowship_deadline(self):
        self.assertEqual(self.check(hkust(), HKUST)[:2], ("verified", "2026-12-01"))
        self.assertEqual(self.check(hkust(local="2 Dec 2026"), HKUST)[0], "ambiguous_deadline")
        for html in (
            hkust().replace("Doctor of Philosophy in Economics", "Master of Science in Finance"),
            hkust().replace("1 Dec 2026", "1 Dec"),
            hkust().replace("Applicants should apply for the PhD program",
                            "Apply for a master's degree"),
            hkust().replace("For 2027/28 Fall Term Intake", "For 2028/29 Fall Term Intake"),
            hkust().replace("For 2027/28 Fall Term Intake", "For 2027/29 Fall Term Intake"),
            hkust().replace("commencing in Sep 2027", "commencing in Sep 2028"),
        ):
            self.assertNotEqual(self.check(html, HKUST)[0], "verified")

    def test_hkust_requires_complete_mode_fields_in_every_current_intake_section(self):
        for html in (
            hkust().replace("Local Applicants Full-time: 1 Dec 2026",
                            "Local Applicants Full-time: 1 Dec 2026 or 2 Dec 2026"),
            hkust().replace("Local Applicants Full-time: 1 Dec 2026",
                            "Local Applicants Full-time: 1 Dec 2026 Full-time: 2 Dec 2026"),
            hkust() + hkust(local="1 Dec"),
            hkust() + hkust().replace("MPhil program is only available", "Other information"),
            hkust() + hkust(local="2 Dec 2026", international="2 Dec 2026"),
        ):
            with self.subTest(html=html):
                self.assertNotEqual(self.check(html, HKUST)[0], "verified")

    def test_york_group_specific_dates_stay_ambiguous(self):
        html = (
            "<h1>Economics</h1><div>Degrees Offered PhD Program Component(s) Dissertation "
            "Deadline - Fall (Domestic Applicants Only) 2027-02-15 "
            "Deadline - Fall (International Applicants Only) 2027-01-15 "
            "English Proficiency Requirement</div>"
        )
        self.assertEqual(self.check(html, YORK)[0], "ambiguous_deadline")
        self.assertEqual(self.check(html.replace("2027-02-15", "2027-01-15"), YORK)[:2],
                         ("verified", "2027-01-15"))
        self.assertNotEqual(self.check(
            html.replace("PhD Program", "MA Program"), YORK,
        )[0], "verified")

    def test_york_checks_all_duplicate_group_labels_and_intake_sections(self):
        for html in (
            york(extra="Deadline - Fall (Domestic Applicants Only) 2027-02-15 "),
            york(extra="Deadline - Fall (Domestic Applicants Only) January 15 "),
            york(domestic="2027-01-15 or 2027-02-15"),
            york() + york(international="January 15"),
            york() + york().replace("English Proficiency", "Other information"),
            york() + york("2027-02-15", "2027-02-15"),
        ):
            with self.subTest(html=html):
                self.assertNotEqual(self.check(html, YORK)[0], "verified")
        self.assertEqual(self.check(york(), YORK)[:2], ("verified", "2027-01-15"))

    def test_york_preserves_the_original_printed_group_dates_in_its_evidence(self):
        status, day, excerpt = self.check(york("15 January 2027", "January 15, 2027"), YORK)
        self.assertEqual((status, day), ("verified", "2027-01-15"))
        self.assertIn("Deadline - Fall (Domestic Applicants Only) 15 January 2027", excerpt)
        self.assertIn("Deadline - Fall (International Applicants Only) January 15, 2027", excerpt)
        self.assertNotIn("2027-01-15", excerpt)
        self.assertLessEqual(len(excerpt), 180)

    def test_date_parser_does_not_accept_invalid_or_yearless_french_dates(self):
        for value in ("1 er février", "31 février 2027", "December 24 (Deadline), 2026"):
            match = DATE_PATTERN.fullmatch(value)
            self.assertIsNone(_parse_date(match) if match else None)


if __name__ == "__main__":
    unittest.main()
