"""Unit tests for the candidate-facing data storage variable sets.

Covers salary parsing, tool vocabulary normalization, degree classification,
start date/term parsing, model coercion, database persistence, and public
JSON serialization.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from predoc_pipeline.core.db import _ADDED_COLUMNS, SCHEMA_VERSION, Database, init
from predoc_pipeline.extract.heuristic import HeuristicExtractor
from predoc_pipeline.models import (
    CANONICAL_TOOLS,
    Discipline,
    ExtractionResult,
    Location,
    PredocListing,
    VisaStatus,
    coerce,
    normalize_degree,
    normalize_start_date,
    normalize_tools,
    parse_salary,
)
from predoc_pipeline.pipeline import _listing_row
from predoc_pipeline.state import _public_record


class TestCandidateNormalization(unittest.TestCase):
    def test_parse_salary_single_annual(self):
        s_min, s_max, curr, period = parse_salary("$65,000 / year")
        self.assertEqual(s_min, 65000.0)
        self.assertEqual(s_max, 65000.0)
        self.assertEqual(curr, "USD")
        self.assertEqual(period, "year")

    def test_parse_salary_range_annual(self):
        s_min, s_max, curr, period = parse_salary("$55,000 - $70,000 per annum")
        self.assertEqual(s_min, 55000.0)
        self.assertEqual(s_max, 70000.0)
        self.assertEqual(curr, "USD")
        self.assertEqual(period, "year")

    def test_parse_salary_k_suffix(self):
        s_min, s_max, curr, period = parse_salary("$55k - 65k / yr")
        self.assertEqual(s_min, 55000.0)
        self.assertEqual(s_max, 65000.0)
        self.assertEqual(curr, "USD")
        self.assertEqual(period, "year")

    def test_parse_salary_hourly_gbp(self):
        s_min, s_max, curr, period = parse_salary("£22.50 per hour")
        self.assertEqual(s_min, 22.5)
        self.assertEqual(s_max, 22.5)
        self.assertEqual(curr, "GBP")
        self.assertEqual(period, "hour")

    def test_parse_salary_monthly_eur(self):
        s_min, s_max, curr, period = parse_salary("€3,200 / month")
        self.assertEqual(s_min, 3200.0)
        self.assertEqual(s_max, 3200.0)
        self.assertEqual(curr, "EUR")
        self.assertEqual(period, "month")

    def test_parse_salary_empty_or_invalid(self):
        self.assertEqual(parse_salary(None), (None, None, None, None))
        self.assertEqual(parse_salary(""), (None, None, None, None))
        self.assertEqual(parse_salary("Competitive salary with benefits"), (None, None, None, None))

    def test_normalize_tools(self):
        raw = ["python", "STATA", "git", "unknown_tool", "python"]
        req, pref = normalize_tools(raw)
        self.assertEqual(req, ["Python", "Stata", "Git"])
        self.assertEqual(pref, [])
        for tool in req:
            self.assertIn(tool, CANONICAL_TOOLS)

    def test_normalize_degree(self):
        self.assertEqual(normalize_degree("Bachelor's degree in Economics")[0], "bachelors")
        self.assertEqual(normalize_degree("B.A. or B.S. required")[0], "bachelors")
        self.assertEqual(normalize_degree("Undergraduate degree")[0], "bachelors")
        self.assertEqual(normalize_degree("Master's degree preferred")[0], "masters")
        self.assertEqual(normalize_degree("M.Sc in Statistics")[0], "masters")
        self.assertEqual(normalize_degree("Ph.D. in related field")[0], "phd")
        self.assertEqual(normalize_degree("Doctorate required")[0], "phd")
        self.assertEqual(normalize_degree("High school diploma")[0], "unstated")
        self.assertEqual(normalize_degree(None), ("unstated", None))

    def test_normalize_start_date(self):
        term1, d1 = normalize_start_date("Fall 2025")
        self.assertEqual(term1, "Fall 2025")
        self.assertIsNone(d1)

        term2, d2 = normalize_start_date("2025-07-01")
        self.assertEqual(term2, "2025-07-01")
        self.assertEqual(d2, "2025-07-01")

        term3, d3 = normalize_start_date("July 2025")
        self.assertEqual(term3, "July 2025")
        self.assertEqual(d3, "2025-07-01")


class TestCoerceAndModel(unittest.TestCase):
    def test_coerce_with_candidate_fields(self):
        raw = ExtractionResult(
            is_vacancy=True,
            title="Predoctoral Fellow",
            institution="Stanford University",
            country="United States",
            city="Stanford",
            is_remote=False,
            duration_years=2,
            deadline="2026-04-01",
            disciplines=["Econometrics"],
            visa_sponsorship_status="explicit",
            application_url="https://stanford.edu/apply",
            summary="A quantitative predoc role.",
            salary_raw="$60,000 - $70,000 / year",
            tools=["Python", "Stata", "Git"],
            min_degree="Bachelor's degree",
            start_date="Fall 2025",
        )
        listing = coerce(raw, source_url="https://stanford.edu/job")
        self.assertIsNotNone(listing)
        self.assertEqual(listing.salary_raw, "$60,000 - $70,000 / year")
        self.assertEqual(listing.salary_min, 60000.0)
        self.assertEqual(listing.salary_max, 70000.0)
        self.assertEqual(listing.salary_currency, "USD")
        self.assertEqual(listing.salary_period, "year")
        self.assertEqual(listing.tools_required, ["Python", "Stata", "Git"])
        self.assertEqual(listing.min_degree, "bachelors")
        self.assertEqual(listing.start_term, "Fall 2025")


class TestDatabaseCandidateVars(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        init(self.db_path)
        self.db = Database(self.db_path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_schema_and_added_columns(self):
        self.assertEqual(SCHEMA_VERSION, 6)
        expected_cols = {
            "salary_raw",
            "salary_min",
            "salary_max",
            "salary_currency",
            "salary_period",
            "tools_required",
            "tools_preferred",
            "min_degree",
            "degree_note",
            "start_date",
            "start_term",
        }
        actual_cols = {col for _, col, _ in _ADDED_COLUMNS}
        for col in expected_cols:
            self.assertIn(col, actual_cols)

    def test_insert_and_retrieve_candidate_vars(self):
        listing = PredocListing(
            title="Predoc Fellow in Economics",
            institution="Harvard University",
            location=Location(country="United States", city="Cambridge", is_remote=False),
            duration_years=2,
            deadline=None,
            disciplines=[Discipline.ECONOMETRICS],
            visa_sponsorship_status=VisaStatus.EXPLICIT,
            apply_url="https://harvard.edu/apply",
            source_url="https://harvard.edu/job/1",
            summary="Join Harvard economics predoc program.",
            salary_raw="$65,000 / yr",
            salary_min=65000.0,
            salary_max=65000.0,
            salary_currency="USD",
            salary_period="year",
            tools_required=["Python", "R", "Stata"],
            tools_preferred=["Git"],
            min_degree="bachelors",
            degree_note="BA in economics or related quantitative field",
            start_date="2025-07-01",
            start_term="Summer 2025",
        )
        row_data = _listing_row(listing, source="test_source", signature=None)
        listing_id = self.db.insert_listing(row_data)
        self.assertIsNotNone(listing_id)

        # Retrieve row directly from database
        row = self.db.listing(listing_id)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["salary_raw"], "$65,000 / yr")
        self.assertEqual(row["salary_min"], 65000.0)
        self.assertEqual(row["salary_currency"], "USD")
        self.assertIn("Python", row["tools_required"])
        self.assertIn("Git", row["tools_preferred"])
        self.assertEqual(row["min_degree"], "bachelors")
        self.assertEqual(row["start_term"], "Summer 2025")

        # Public record serialization
        record = _public_record(row)
        self.assertEqual(record["salary_raw"], "$65,000 / yr")
        self.assertEqual(record["salary_min"], 65000.0)
        self.assertEqual(record["tools_required"], ["Python", "R", "Stata"])
        self.assertEqual(record["tools_preferred"], ["Git"])
        self.assertEqual(record["min_degree"], "bachelors")
        self.assertEqual(record["start_term"], "Summer 2025")


class TestHeuristicCandidateExtraction(unittest.TestCase):
    def test_from_text_extracts_candidate_fields(self):
        content = """
        Harvard University
        Predoctoral Research Fellow in Economics
        Compensation: $62,000 per year.
        Requirements: Bachelor's degree in Economics, Mathematics, or Computer Science.
        Strong proficiency with Python and Stata required.
        Application deadline: 2026-06-01. Position starts Fall 2025.
        Apply at: https://harvard.edu/apply-now
        """
        extractor = HeuristicExtractor()
        res = extractor.extract(
            text=content,
            source_url="https://harvard.edu/job",
            title="Predoctoral Research Fellow",
        )
        self.assertTrue(res.is_vacancy)
        self.assertEqual(res.salary_raw, "$62,000 per year")
        self.assertIn("Python", res.tools)
        self.assertIn("Stata", res.tools)
        self.assertEqual(res.min_degree, "bachelor's")
        self.assertEqual(res.start_date, "Fall 2025")

        # Coerce into final listing
        listing = coerce(res, source_url="https://harvard.edu/job")
        self.assertEqual(listing.salary_min, 62000.0)
        self.assertEqual(listing.salary_max, 62000.0)
        self.assertEqual(listing.salary_currency, "USD")
        self.assertEqual(listing.min_degree, "bachelors")
        self.assertEqual(listing.start_term, "Fall 2025")
        self.assertIn("Python", listing.tools_required)
        self.assertIn("Stata", listing.tools_required)
