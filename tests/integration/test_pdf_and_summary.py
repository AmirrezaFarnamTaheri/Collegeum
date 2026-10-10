"""Tests for PDF extraction utility and summary sanitization."""
from __future__ import annotations

import io
import unittest
from datetime import UTC

from predoc_pipeline.models import sanitize_summary
from predoc_pipeline.utils.pdf import clean_pdf_text, extract_pdf_text, is_pdf


class TestPdfExtraction(unittest.TestCase):
    def test_is_pdf(self):
        self.assertTrue(is_pdf(b"%PDF-1.6 something"))
        self.assertTrue(is_pdf("%PDF-1.4 header"))
        self.assertTrue(is_pdf(b"", content_type="application/pdf"))
        self.assertTrue(is_pdf(b"", url="https://example.org/job.pdf"))
        self.assertTrue(is_pdf(b"", url="https://example.org/job.PDF?query=1"))
        self.assertFalse(is_pdf(b"<html>hello</html>", content_type="text/html", url="https://example.org/job"))

    def test_extract_pdf_text_with_pypdf(self):
        import pypdf

        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=72, height=72)
        stream = io.BytesIO()
        writer.write(stream)
        pdf_bytes = stream.getvalue()

        self.assertTrue(is_pdf(pdf_bytes))
        # Blank page extracts cleanly without error
        text = extract_pdf_text(pdf_bytes)
        self.assertEqual(text, "")

    def test_extract_pdf_corrupted_data(self):
        corrupted = b"%PDF-corrupted-binary-garbage\x00\xff\xfe"
        text = extract_pdf_text(corrupted)
        self.assertEqual(text, "")

    def test_clean_pdf_text(self):
        raw = "  Line 1   \n\n   \n  Line 2   with   spaces  \n"
        cleaned = clean_pdf_text(raw)
        self.assertEqual(cleaned, "Line 1\nLine 2 with spaces")


class TestSummarySanitization(unittest.TestCase):
    def test_strips_pdf_stream_leak(self):
        pdf_leak = "%PDF-1.6 % 41 0 obj <> endobj 64 0 obj <>/Filter/FlateDecode stream hbbd`..."
        result = sanitize_summary(
            pdf_leak,
            title="Research Professional",
            institution="University of Chicago Booth",
            pi="Eric Budish",
        )
        self.assertNotIn("%PDF-", result)
        self.assertIn("University of Chicago Booth", result)
        self.assertIn("Eric Budish", result)

    def test_parses_pipe_delimited_summary(self):
        pipe_summary = (
            "pi_name: Robert Metcalfe | institution: Columbia University | "
            "fields: Environmental, Data Science, Labor | deadline: October 7, 2026"
        )
        result = sanitize_summary(pipe_summary)
        self.assertNotIn("pi_name:", result)
        self.assertNotIn(" | ", result)
        self.assertIn("Columbia University", result)
        self.assertIn("Robert Metcalfe", result)
        self.assertIn("Environmental, Data Science, Labor", result)
        self.assertIn("October 7, 2026", result)

    def test_german_boilerplate_replaced_with_english(self):
        german_summary = (
            "Zur Verstärkung unseres Teams suchen wir eine/n wissenschaftliche:r Mitarbeiter:in. "
            "Ihre Aufgaben umfassen die Mitarbeit an einem Forschungsprojekt. Vergütung nach TV-L."
        )
        result = sanitize_summary(german_summary, institution="TU Ilmenau")
        self.assertNotIn("Verstärkung", result)
        self.assertIn("Position at TU Ilmenau", result)
        self.assertIn("original-language advert", result)
        self.assertNotIn("doctoral studies", result)
        self.assertNotIn("academic coursework", result)

    def test_empty_summary_fallback(self):
        result = sanitize_summary(
            "",
            title="Pre-Doctoral Fellow",
            institution="Warwick University",
            pi="Sonia Bhalotra",
        )
        self.assertIn("Warwick University", result)
        self.assertIn("Sonia Bhalotra", result)

    def test_strips_browser_warning_banner(self):
        banner = (
            "Please switch to a supported browser listed here , "
            "or some features may not work correctly."
        )
        result = sanitize_summary(
            banner,
            title="Research Assistant",
            institution="National Bureau of Economic Research",
            pi="Joseph Shapiro",
        )
        self.assertNotIn("supported browser", result)
        self.assertIn("National Bureau of Economic Research", result)
        self.assertIn("Joseph Shapiro", result)

    def test_strips_skip_links_and_navigation(self):
        text = "Skip to main content Back to search results Research Fellow at UCL"
        result = sanitize_summary(text)
        self.assertFalse(result.lower().startswith("skip to"))
        self.assertFalse(result.lower().startswith("back to search"))
        self.assertIn("Research Fellow at UCL", result)

    def test_sponsoring_researcher_pattern(self):
        text = (
            "Sponsoring Researcher : Bureau of Economics "
            "Sponsoring Institution : U.S. Federal Trade Commission "
            "Fields of Research : Microeconomics, Statistics "
            "Deadline : October 15, 2026"
        )
        result = sanitize_summary(text)
        self.assertIn("Research position at U.S. Federal Trade Commission", result)
        self.assertNotIn("Predoctoral", result)
        self.assertIn("Bureau of Economics", result)
        self.assertIn("Research focus includes Microeconomics, Statistics", result)

    def test_about_us_preamble_stripped(self):
        text = (
            "Research Fellow UCL - School of Management Location: London Salary: £43,000 "
            "About us The UCL School of Management is home to world-leading research."
        )
        result = sanitize_summary(text)
        self.assertFalse(result.startswith("Research Fellow UCL - School of Management Location"))
        self.assertTrue(result.startswith("The UCL School of Management is home to"))


class TestPendingAndDeadlineLogic(unittest.TestCase):
    def test_deadline_label_same_day(self):
        from datetime import datetime

        from predoc_pipeline.publish.telegram import deadline_label

        today_str = datetime.now(UTC).strftime("%Y-%m-%dT12:00:00Z")
        label = deadline_label(today_str)
        self.assertIn("today", label)

    def test_pending_listings_queries_unbroadcast(self):
        import tempfile
        from pathlib import Path

        from predoc_pipeline.core.db import Database, init
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            init(db_path)
            with Database(db_path) as db:
                db.import_rows([
                    {
                        "url_hash": "h1",
                        "title": "Pending Predoc 1",
                        "institution": "Inst 1",
                        "apply_url": "https://example.org/1",
                        "source_url": "https://example.org/1",
                        "status": "pending",
                        "telegram_message_id": None,
                        "first_seen_at": "2026-10-04T00:00:00Z",
                        "last_seen_at": "2026-10-04T00:00:00Z",
                    },
                    {
                        "url_hash": "h2",
                        "title": "Predoc 2",
                        "institution": "Inst 2",
                        "apply_url": "https://example.org/2",
                        "source_url": "https://example.org/2",
                        "status": "published",
                        "telegram_message_id": 12,
                        "first_seen_at": "2026-10-04T00:00:00Z",
                        "last_seen_at": "2026-10-04T00:00:00Z",
                    },
                ])
                pending = db.pending_listings()
                ids = [p["url_hash"] for p in pending]
                self.assertIn("h1", ids)
                self.assertNotIn("h2", ids)

