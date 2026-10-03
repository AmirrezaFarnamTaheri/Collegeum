"""Tests for X API v2 and Xquik social ingestion collectors."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from predoc_pipeline.ingest.collectors import (
    collect_twitter,
    collect_x_api,
    collect_xquik,
)
from predoc_pipeline.settings import Settings


class TestXIngest(unittest.TestCase):
    def test_collect_x_api_success(self):
        settings = Settings(x_bearer_token="mock_bearer_token")
        settings.twitter_search_queries = ["from:econ_RA"]
        settings.twitter_search_accounts = []

        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "id": "1800111222",
                    "text": "Harvard hiring predoc in labor economics! Apply at https://t.co/abc",
                    "author_id": "user_100",
                    "entities": {
                        "urls": [
                            {
                                "url": "https://t.co/abc",
                                "expanded_url": "https://opportunityinsights.org/predoc-call",
                            }
                        ]
                    },
                }
            ],
            "includes": {
                "users": [{"id": "user_100", "username": "econ_RA", "name": "Econ RA"}]
            },
        }
        mock_http.get.return_value = mock_resp

        items, stats = collect_x_api(settings, client=mock_http)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "twitter:@econ_RA")
        self.assertEqual(items[0].source_url, "https://x.com/econ_RA/status/1800111222")
        self.assertIn("opportunityinsights.org", items[0].text)
        self.assertEqual(stats[0].items, 1)
        self.assertEqual(stats[0].errors, 0)

    def test_collect_x_api_rate_limited(self):
        settings = Settings(x_bearer_token="mock_bearer_token")
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_http.get.return_value = mock_resp

        items, stats = collect_x_api(settings, client=mock_http)
        self.assertEqual(len(items), 0)
        self.assertEqual(stats[0].errors, 1)
        self.assertIn("rate limited", stats[0].messages[0].lower())

    def test_collect_xquik_success(self):
        settings = Settings(xquik_api_key="xq_mock_key")
        settings.twitter_search_queries = ["from:econ_RA"]

        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "id": "2000333",
                    "text": "Stanford predoc fellowship open for 2026",
                    "username": "siepr",
                }
            ]
        }
        mock_http.get.return_value = mock_resp

        items, stats = collect_xquik(settings, client=mock_http)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "xquik:@siepr")
        self.assertIn("Stanford predoc", items[0].title)

    def test_collect_twitter_routing_no_creds(self):
        settings = Settings()
        settings.x_bearer_token = ""
        settings.xquik_api_key = ""
        import os
        old_env = os.environ.copy()
        try:
            os.environ.pop("X_BEARER_TOKEN", None)
            os.environ.pop("XQUIK_API_KEY", None)
            os.environ.pop("TWSCRAPE_ACCOUNTS", None)
            items, stats = collect_twitter(settings)
            self.assertEqual(len(items), 0)
            self.assertIn("No X/Twitter ingestion credentials found", stats[0].messages[0])
        finally:
            os.environ.clear()
            os.environ.update(old_env)


if __name__ == "__main__":
    unittest.main()
