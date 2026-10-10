"""Unit and integration tests for X (Twitter) client, formatting, and broadcasting."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from predoc_pipeline.core.db import Database
from predoc_pipeline.core.db import init as init_db
from predoc_pipeline.models import Discipline, Location, PredocListing, VisaStatus
from predoc_pipeline.publish.x import (
    XClient,
    XError,
    format_thread,
    format_tweet,
    tweet_length,
)


def _sample_listing(
    title: str = "Predoctoral Research Associate",
    institution: str = "Paris School of Economics",
    city: str = "Paris",
    country: str = "France",
    apply_url: str = "https://www.parisschoolofeconomics.eu/apply/predoc-2026",
    summary: str = "Empirical research assistantship focusing on labor markets.",
) -> PredocListing:
    return PredocListing(
        title=title,
        institution=institution,
        location=Location(city=city, country=country, is_remote=False),
        apply_url=apply_url,
        source_url="https://www.parisschoolofeconomics.eu/jobs",
        summary=summary,
        disciplines=[Discipline.APPLIED_MICRO, Discipline.PUBLIC_POLICY],
        visa_sponsorship_status=VisaStatus.EXPLICIT,
        visa_note="French talent passport supported",
        confidence=0.95,
        model_confidence=0.92,
        rule_score=1.0,
    )


class TestXFormatting(unittest.TestCase):
    def test_tweet_length_standard(self):
        text = "Hello world! This is a test tweet."
        self.assertEqual(tweet_length(text), len(text))

    def test_tweet_length_urls_count_as_23(self):
        # A 50-char URL counts as 23
        long_url = "https://example.org/very/long/path/to/some/job/posting/with/many/parameters"
        text = f"Check this job: {long_url}"
        expected = len("Check this job: ") + 23
        self.assertEqual(tweet_length(text), expected)

    def test_format_tweet_within_budget(self):
        listing = _sample_listing()
        tweet = format_tweet(listing)
        self.assertIn("Paris School of Economics", tweet)
        self.assertIn("Predoctoral Research Associate", tweet)
        self.assertIn("Paris, France", tweet)
        self.assertIn("#EconTwitter", tweet)
        self.assertLessEqual(tweet_length(tweet), 280)

    def test_format_tweet_very_long_title_truncated_to_fit(self):
        long_title = "Predoc " + ("very long title research assistant in economics " * 10)
        listing = _sample_listing(title=long_title)
        tweet = format_tweet(listing)
        self.assertLessEqual(tweet_length(tweet), 280)
        self.assertIn("#EconTwitter", tweet)

    def test_format_thread(self):
        listing = _sample_listing()
        thread = format_thread(listing)
        self.assertEqual(len(thread), 2)
        self.assertIn("Paris School of Economics", thread[0])
        self.assertIn("Details:", thread[1])
        self.assertIn("labor markets", thread[1])
        for tweet in thread:
            self.assertLessEqual(tweet_length(tweet), 280)


class TestXClient(unittest.TestCase):
    def test_post_tweet_success(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"data": {"id": "189000111222333444"}}
        mock_session.post.return_value = mock_resp

        client = XClient(
            consumer_key="key",
            consumer_secret="secret",
            access_token="tok",
            access_token_secret="sec",
            session=mock_session,
        )
        tweet_id = client.post_tweet("Hello from predoc bot!")
        self.assertEqual(tweet_id, "189000111222333444")
        mock_session.post.assert_called_once()

    def test_post_tweet_missing_id_raises(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"data": {}}
        mock_session.post.return_value = mock_resp

        client = XClient(
            consumer_key="key",
            consumer_secret="secret",
            access_token="tok",
            access_token_secret="sec",
            session=mock_session,
        )
        with self.assertRaises(XError) as ctx:
            client.post_tweet("Hello from predoc bot!")
        self.assertIn("missing valid tweet id", str(ctx.exception))

    def test_post_tweet_rate_limited(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {"x-rate-limit-reset": "1730000000"}
        mock_resp.text = "Rate limit exceeded"
        mock_session.post.return_value = mock_resp

        client = XClient(
            consumer_key="k",
            consumer_secret="s",
            access_token="t",
            access_token_secret="sec",
            session=mock_session,
        )
        with self.assertRaises(XError) as ctx:
            client.post_tweet("Testing rate limit")
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(ctx.exception.reset_ts, 1730000000)

    def test_post_tweet_forbidden(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.json.return_value = {"detail": "You are not allowed to create a tweet"}
        mock_session.post.return_value = mock_resp

        client = XClient(
            consumer_key="k",
            consumer_secret="s",
            access_token="t",
            access_token_secret="sec",
            session=mock_session,
        )
        with self.assertRaises(XError) as ctx:
            client.post_tweet("Testing 403")
        self.assertEqual(ctx.exception.status, 403)
        self.assertTrue(ctx.exception.permanent)

    def test_search_recent(self):
        mock_http = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "id": "111",
                    "text": "We are hiring a predoc! Apply here: https://t.co/xyz",
                    "author_id": "1001",
                    "entities": {
                        "urls": [{"url": "https://t.co/xyz", "expanded_url": "https://jobs.example.org/predoc"}]
                    },
                }
            ],
            "includes": {"users": [{"id": "1001", "username": "econ_RA", "name": "Econ RA"}]},
        }
        mock_http.get.return_value = mock_resp

        client = XClient(bearer_token="mock_bearer")
        results = client.search_recent("from:econ_RA", http_client=mock_http)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "111")
        self.assertEqual(results[0]["author"]["username"], "econ_RA")


class TestPipelineXBroadcasting(unittest.TestCase):
    def test_broadcast_records_x_post_id(self):
        import tempfile
        from pathlib import Path

        from predoc_pipeline.pipeline import RunStats, _broadcast
        from predoc_pipeline.settings import Settings

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "test.db")
            init_db(db_path)
            db = Database(db_path)
            try:
                listing = _sample_listing(country="United States", city="Cambridge, MA")
                from predoc_pipeline.pipeline import _listing_row
                row_data = _listing_row(listing, source="test", signature=None)
                lid = db.insert_listing(row_data)

                mock_x = MagicMock()
                mock_x.post_listing.return_value = "tweet_999888"

                from predoc_pipeline.boards.config import Preferences
                from predoc_pipeline.routing import Router
                settings = Settings()
                stats = RunStats()
                router = Router(Preferences())

                _broadcast(
                    [(lid, listing)],
                    telegram=None,
                    settings=settings,
                    db=db,
                    stats=stats,
                    x_client=mock_x,
                    router=router,
                )

                mock_x.post_listing.assert_called_once()
                row = db.listing(lid)
                self.assertIsNotNone(row)
                self.assertEqual(row["x_post_id"], "tweet_999888")
                self.assertEqual(row["status"], "published")
                self.assertEqual(stats.published, 1)
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
