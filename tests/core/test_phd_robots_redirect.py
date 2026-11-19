"""Robots policy must be enforced on HTTP redirect destinations before fetching."""
from __future__ import annotations

import urllib.request
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from tools.update_phd_admissions import (
    OfficialOnlyRedirect,
    check_official_url,
)

NOW = datetime(2026, 11, 19, 14, 0, tzinfo=UTC)
HOST = "university.example.edu"


class OfficialRedirectRobotsTests(unittest.TestCase):
    def test_disallowed_same_host_redirect_is_refused_before_following(self):
        seen = []

        def robots_allowed(url: str) -> bool:
            seen.append(url)
            return not url.endswith("/private/doctoral-applicants")

        handler = OfficialOnlyRedirect(HOST, robots_allowed=robots_allowed)
        req = urllib.request.Request(f"https://{HOST}/economics-phd")
        with self.assertRaisesRegex(ValueError, "robots_disallowed_redirect"):
            handler.redirect_request(
                req, None, 302, "Found", {},
                f"https://{HOST}/private/doctoral-applicants",
            )
        self.assertEqual(
            seen, [f"https://{HOST}/private/doctoral-applicants"],
        )

    def test_allowed_same_host_redirect_does_not_block_the_request(self):
        handler = OfficialOnlyRedirect(
            HOST, robots_allowed=lambda url: not url.endswith("/private"),
        )
        req = urllib.request.Request(f"https://{HOST}/economics-phd")
        redirected = handler.redirect_request(
            req, None, 302, "Found", {},
            f"https://{HOST}/phd/admissions",
        )
        self.assertIsNotNone(redirected)
        self.assertEqual(redirected.full_url, f"https://{HOST}/phd/admissions")

    def test_production_checker_passes_robots_policy_into_page_fetch(self):
        actual = []

        def fake_read(url: str, **kwargs):
            if url.endswith("/robots.txt"):
                return (
                    200,
                    b"User-agent: *\nDisallow: /private\n",
                    url,
                )
            policy = kwargs.get("allowed_redirect")
            self.assertIsNotNone(policy)
            actual.append(policy(f"https://{HOST}/private/doctoral-applicants"))
            actual.append(policy(f"https://{HOST}/phd/apply"))
            return (
                200,
                b"<h1>Economics PhD admissions</h1>"
                b"<p>Application deadline: 15 January 2027.</p>",
                url,
            )

        with patch("tools.update_phd_admissions._read_url", side_effect=fake_read):
            observation = check_official_url(f"https://{HOST}/phd", now=NOW)
        self.assertEqual(observation["status"], "verified")
        self.assertEqual(actual, [False, True])


if __name__ == "__main__":
    unittest.main()
