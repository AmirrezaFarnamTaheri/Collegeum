"""Tests for PDF extraction utility and summary sanitization."""
from __future__ import annotations

import io
import unittest

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
        self.assertIn("Research assistant position at TU Ilmenau", result)
        self.assertIn("doctoral studies", result)

    def test_empty_summary_fallback(self):
        result = sanitize_summary(
            "",
            title="Pre-Doctoral Fellow",
            institution="Warwick University",
            pi="Sonia Bhalotra",
        )
        self.assertIn("Warwick University", result)
        self.assertIn("Sonia Bhalotra", result)
