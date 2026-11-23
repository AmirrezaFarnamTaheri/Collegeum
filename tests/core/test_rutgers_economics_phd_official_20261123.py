"""Rutgers New Brunswick has a dated, programme-specific Economics PhD directory.

Do not treat the School of Graduate Studies yearless departmental FAQ as
officially current. Only the university's current-year Economics PHD New
Brunswick admissions row can verify an application deadline.
"""
from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tools.update_phd_admissions import collect_official_deadline, validate_catalogues

NOW = datetime(2026, 11, 23, 12, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]
RUTGERS = (
    "https://grad.admissions.rutgers.edu/GraduateProgram/"
    "Detail.aspx?id=a501U0000004gNmQAI"
)


def rutgers_directory(
    *, programme: str = "Economics (PHD) New Brunswick",
    us: str = "Jan 15, 2027", overseas: str = "Jan 15, 2027",
    include_2027: bool = True, extra: str = "",
) -> str:
    current = (
        f"<tr><td>Fall 2027</td><td>{us}</td><td>{overseas}</td></tr>"
        if include_2027 else ""
    )
    return (
        "<p>Graduate and Professional Admissions</p>"
        f"<h1>{programme}</h1>"
        "<h2>Deadlines</h2>"
        "<table><tr><th>Intake</th><th>U.S.</th><th>Non-U.S.</th></tr>"
        + current
        + "<tr><td>Fall 2028</td><td>Jan 15, 2028</td>"
        "<td>Jan 15, 2028</td></tr>"
        + extra
        + "</table>"
        "<h2>The School of Graduate Studies - New Brunswick</h2>"
        "<h3>Program Requirements</h3>"
        "<p>Official GRE scores are required.</p>"
    )


class RutgersEconomicsPhdCurrentYearSourceTests(unittest.TestCase):
    def test_fall_2027_us_and_non_us_identical_deadline_is_current(self):
        status, date, excerpt = collect_official_deadline(
            rutgers_directory(), now=NOW, source_url=RUTGERS,
        )
        self.assertEqual((status, date), ("verified", "2027-01-15"))
        self.assertIn("2027", excerpt)
        self.assertNotIn("2028", excerpt)

    def test_2028_deadline_is_not_inferred_as_current_2027(self):
        status, date, excerpt = collect_official_deadline(
            rutgers_directory(include_2027=False), now=NOW, source_url=RUTGERS,
        )
        self.assertNotEqual(status, "verified")
        self.assertIsNone(date)
        self.assertIsNone(excerpt)

    def test_domestic_international_conflict_fails_closed(self):
        status, date, _ = collect_official_deadline(
            rutgers_directory(overseas="Jan 20, 2027"), now=NOW,
            source_url=RUTGERS,
        )
        self.assertEqual(status, "ambiguous_deadline")
        self.assertIsNone(date)

    def test_yearless_expired_and_unrelated_programme_not_confirmed(self):
        for html, url in (
            (rutgers_directory(us="Jan 15", overseas="Jan 15"), RUTGERS),
            (rutgers_directory(us="Jan 15, 2025",
                               overseas="Jan 15, 2025"), RUTGERS),
            (rutgers_directory(programme="Economics (MA) New Brunswick"), RUTGERS),
            (rutgers_directory(programme="Economics (PHD) Newark"), RUTGERS),
            (rutgers_directory(programme="Statistics (PHD) New Brunswick"), RUTGERS),
            (rutgers_directory(), RUTGERS.replace("4gNmQAI", "4gLxQAI")),
            (rutgers_directory(), "https://other.example.edu/GraduateProgram/"
             "Detail.aspx?id=a501U0000004gNmQAI"),
        ):
            with self.subTest(url=url, html=html):
                self.assertNotEqual(
                    collect_official_deadline(html, now=NOW,
                                              source_url=url)[0], "verified",
                )

    def test_conflicting_fall_2027_rows_cannot_be_combined(self):
        duplicate = (
            "<tr><td>Fall 2027</td><td>Jan 18, 2027</td>"
            "<td>Jan 18, 2027</td></tr>"
        )
        result = collect_official_deadline(
            rutgers_directory(extra=duplicate), now=NOW, source_url=RUTGERS,
        )
        self.assertEqual(result[0], "ambiguous_deadline")

    def test_source_repair_keeps_251_and_all_prior_verifications(self):
        seeds = json.loads(
            (ROOT / "config/phd_admissions_seeds.json").read_text(encoding="utf-8")
        )
        public = json.loads(
            (ROOT / "docs/data/phd_admissions.json").read_text(encoding="utf-8")
        )
        validate_catalogues(seeds, public)
        self.assertEqual(len(seeds["programmes"]), 251)
        self.assertEqual(len(public["programmes"]), 251)
        seed = next(x for x in seeds["programmes"]
                    if x["institution"] == "Rutgers University-New Brunswick")
        row = next(x for x in public["programmes"]
                   if x["institution"] == "Rutgers University-New Brunswick")
        self.assertEqual(seed["official_programme_url"], RUTGERS)
        self.assertEqual(row["official_programme_url"], RUTGERS)
        if row["status"] == "verified":
            self.assertEqual(row["deadline_iso"], "2027-01-15")
            self.assertEqual(row["evidence_url"], RUTGERS)
        else:
            self.assertIsNone(row["deadline_iso"])


if __name__ == "__main__":
    unittest.main()
