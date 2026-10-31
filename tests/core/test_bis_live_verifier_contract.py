"""Protect the BIS manual live probe when adding job-level location evidence."""
from __future__ import annotations

import unittest
from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/verify-bis-official-rss-live.yml"
)


class BisLiveVerifierContractTests(unittest.TestCase):
    def test_probe_accepts_evidenced_country_instead_of_requiring_unknown(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("assert job.country is None,", content)
        self.assertNotIn("assert job.country is None\n", content)
        self.assertIn("job.location", content)

    def test_probe_survives_normal_recruitment_turnover(self):
        """A closed job must not make a healthy employer feed fail verification."""
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn('assert hong_kong,', content)
        self.assertNotIn('assert any(j.country == "Switzerland" for j in jobs)', content)

    def test_probe_still_forbids_implicit_employer_headquarters(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('source_country_default', content)
        self.assertIn("job.country", content)


if __name__ == "__main__":
    unittest.main()
