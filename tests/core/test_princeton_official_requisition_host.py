"""Princeton RPDE must accept its two verified official iCIMS hostnames only."""
from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PrincetonOfficialRequisitionTests(unittest.TestCase):
    def test_rpde_accepts_new_and_legacy_official_requisition_links_only(self):
        with (ROOT / "config/sources.toml").open("rb") as stream:
            boards = tomllib.load(stream)["board"]
        source = next(board for board in boards if board["name"] == "princeton_rpde_jobs")
        self.assertFalse(source["enabled"], "Runner verification is still required")
        pattern = source["link_pattern"]
        allowed = (
            "https://research-princeton.icims.com/jobs/22348/senior-research-specialist/job",
            "https://main-princeton.icims.com/jobs/4583/senior-research-specialist/job",
        )
        forbidden = (
            "http://research-princeton.icims.com/jobs/22348/senior-research-specialist/job",
            ("https://research-princeton.icims.com.evil.org/jobs/22348/"
             "senior-research-specialist/job"),
            "https://fake-research-princeton.icims.com/jobs/22348/senior-research-specialist/job",
            "https://careers-brookings.icims.com/jobs/22348/senior-research-specialist/job",
            "https://research-princeton.icims.com/about/jobs",
        )
        for url in allowed:
            with self.subTest(allowed=url):
                self.assertIsNotNone(re.search(pattern, url))
        for url in forbidden:
            with self.subTest(forbidden=url):
                self.assertIsNone(re.search(pattern, url))
        self.assertNotEqual(allowed[0], allowed[1])


if __name__ == "__main__":
    unittest.main()
