"""Integration tests for the Gemini extraction backends.

These require httpx, pydantic and respx, none of which are part of the
dependency-free core, so the whole module is skipped when they are absent
rather than failing collection. This addresses a defect in the reviewed
implementation, which declared respx as a test dependency but never wrote a
test that used it -- so the retry, backoff and 429-handling logic had never
actually been exercised.
"""

from __future__ import annotations

import json
import unittest

try:
    import httpx
    import respx

    from predoc_pipeline.core.ratelimit import RateLimiter
    from predoc_pipeline.extract.gemini import ExtractionError, Extractor, RateLimited

    DEPS_AVAILABLE = True
except ImportError:
    DEPS_AVAILABLE = False

# `@respx.mock` is evaluated when the class body executes, which happens
# before `unittest.skipUnless` has a chance to skip anything -- so decorating
# methods with it directly would raise NameError whenever respx is absent,
# defeating the whole point of the availability guard above. This local alias
# is a no-op passthrough in that case, and every test method below decorates
# with `@respx_mock` rather than `@respx.mock` for exactly this reason.
if DEPS_AVAILABLE:
    respx_mock = respx.mock
else:  # pragma: no cover - exercised only when the optional deps are absent
    def respx_mock(func):
        return func


def _generate_content_success(text: dict) -> dict:
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": json.dumps(text)}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"totalTokenCount": 123},
    }


def _interactions_success(text: dict) -> dict:
    return {"output_text": json.dumps(text)}


VALID_RESULT = {
    "is_vacancy": True,
    "rejection_reason": None,
    "title": "Predoctoral Research Assistant",
    "institution": "Example University",
    "principal_investigator": None,
    "country": "United Kingdom",
    "city": "London",
    "is_remote": False,
    "duration_years": 2,
    "deadline": "2027-03-01",
    "disciplines": ["Applied Microeconomics"],
    "visa_sponsorship_status": "unknown",
    "application_url": None,
    "summary": "A two year predoctoral research role.",
    "confidence": 0.92,
}


@unittest.skipUnless(DEPS_AVAILABLE, "requires httpx, respx and pydantic")
class TestExtractorBackendProbing(unittest.TestCase):
    def _extractor(self, **kwargs) -> Extractor:
        limiter = RateLimiter(requests_per_minute=600, requests_per_day=1000)
        return Extractor(
            api_key="test-key",
            model="gemini-flash-lite-latest",
            base_url="https://generativelanguage.googleapis.com",
            limiter=limiter,
            **kwargs,
        )

    @respx_mock
    def test_interactions_backend_succeeds_first(self):
        respx.post("https://generativelanguage.googleapis.com/v1beta/interactions").mock(
            return_value=httpx.Response(200, json=_interactions_success(VALID_RESULT))
        )
        extractor = self._extractor(backend="auto")
        result = extractor.extract(text="a" * 100, source_url="https://example.org/x")
        self.assertTrue(result.is_vacancy)
        self.assertEqual(result.institution, "Example University")

    @respx_mock
    def test_falls_back_to_generate_content_on_404(self):
        respx.post("https://generativelanguage.googleapis.com/v1beta/interactions").mock(
            return_value=httpx.Response(404, json={"error": {"message": "not found"}})
        )
        respx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-flash-lite-latest:generateContent"
        ).mock(return_value=httpx.Response(200, json=_generate_content_success(VALID_RESULT)))
        extractor = self._extractor(backend="auto")
        result = extractor.extract(text="a" * 100, source_url="https://example.org/x")
        self.assertTrue(result.is_vacancy)

    @respx_mock
    def test_429_raises_rate_limited_with_retry_delay(self):
        respx.post("https://generativelanguage.googleapis.com/v1beta/interactions").mock(
            return_value=httpx.Response(
                429,
                json={
                    "error": {
                        "message": "rate limited",
                        "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo",
                                     "retryDelay": "12s"}],
                    }
                },
            )
        )
        extractor = self._extractor(backend="interactions")
        with self.assertRaises(RateLimited) as ctx:
            extractor.extract(text="a" * 100, source_url="https://example.org/x")
        self.assertAlmostEqual(ctx.exception.retry_after, 12.0)

    @respx_mock
    def test_permanent_400_does_not_retry_forever(self):
        route = respx.post(
            "https://generativelanguage.googleapis.com/v1beta/interactions"
        ).mock(return_value=httpx.Response(400, json={"error": {"message": "bad schema"}}))
        extractor = self._extractor(backend="interactions")
        with self.assertRaises(ExtractionError):
            extractor.extract(text="a" * 100, source_url="https://example.org/x")
        # Exactly one attempt: a single fixed backend on a 400 must not retry.
        self.assertEqual(route.call_count, 1)

    @respx_mock
    def test_backend_choice_is_cached_in_store(self):
        respx.post("https://generativelanguage.googleapis.com/v1beta/interactions").mock(
            return_value=httpx.Response(404, json={"error": {}})
        )
        respx.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-flash-lite-latest:generateContent"
        ).mock(return_value=httpx.Response(200, json=_generate_content_success(VALID_RESULT)))

        class FakeStore:
            def __init__(self):
                self.saved = None

            def get_meta(self, key):
                return self.saved

            def set_meta(self, key, value):
                self.saved = value

        store = FakeStore()
        extractor = self._extractor(backend="auto", store=store)
        extractor.extract(text="a" * 100, source_url="https://example.org/x")
        self.assertEqual(store.saved, "generate_content")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
