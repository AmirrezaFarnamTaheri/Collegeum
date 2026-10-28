"""Regression tests for actionable, non-sensitive public source health."""
from __future__ import annotations

import json
import unittest

from predoc_pipeline.core.health import public_failure, public_source_stats, source_summary


class PublicHealthDiagnosticsTests(unittest.TestCase):
    def test_limit_failure_is_not_misreported_as_a_network_failure(self) -> None:
        self.assertEqual(
            public_failure("3 discovery limit(s) reached"),
            "Discovery truncated by configured limit",
        )

    def test_public_counts_preserve_only_known_numeric_failure_categories(self) -> None:
        result = public_source_stats({
            "board:example": {
                "kind": "board",
                "items": 15,
                "errors": 3,
                "ok": False,
                "failure_counts": {
                    "fetch": 1,
                    "parse": 1,
                    "limit": 1,
                    "access_token": "do-not-publish",
                },
                "failure_stage": "fetch/parse/limit",
                "messages": ["POST https://example.test/?token=do-not-publish"],
            }
        })
        source = result["board:example"]
        self.assertEqual(source["failure_counts"], {"fetch": 1, "parse": 1, "limit": 1})
        self.assertEqual(source["failure_stage"], "fetch/parse/limit")
        self.assertNotIn("do-not-publish", json.dumps(result))

    def test_public_counts_reject_invalid_values_and_untrusted_stages(self) -> None:
        result = public_source_stats({
            "board:example": {
                "kind": "board", "ok": False, "items": 0, "errors": 1,
                "failure_counts": {"fetch": -2, "parse": "secret", "limit": True},
                "failure_stage": "https://example.test/?token=private",
            }
        })["board:example"]
        self.assertEqual(result["failure_counts"], {"fetch": 0, "parse": 0, "limit": 0})
        self.assertNotIn("failure_stage", result)
        self.assertNotIn("private", json.dumps(result))


    def test_public_source_status_reconciles_successful_fetch_with_unexpected_empty(self) -> None:
        """A source may fetch successfully yet be unhealthy when vacancies are missing."""
        raw = {
            "board:eth": {
                "kind": "board", "items": 0, "raw": 0, "fetched": 1,
                "ok": True, "errors": 0, "may_be_empty": False, "messages": [],
            },
            "board:niesr": {
                "kind": "board", "items": 0, "raw": 0, "fetched": 1,
                "ok": True, "errors": 0, "may_be_empty": True, "messages": [],
            },
            "board:crest": {
                "kind": "board", "items": 0, "fetched": 0,
                "ok": False, "errors": 1, "messages": ["HTTP 503 for https://hidden.test/?token=secret"],
            },
            "board:ubc": {
                "kind": "board", "items": 34, "fetched": 0,
                "ok": False, "errors": 2, "messages": ["2 payloads parsed incompletely"],
            },
            "board:zew": {
                "kind": "board", "items": 7, "fetched": 1,
                "ok": True, "errors": 0, "messages": [],
            },
        }
        public = public_source_stats(raw)
        self.assertEqual(
            {name: item["status"] for name, item in public.items()},
            {
                "board:eth": "failed",
                "board:niesr": "empty",
                "board:crest": "failed",
                "board:ubc": "partial",
                "board:zew": "successful",
            },
        )
        self.assertEqual(source_summary(public), source_summary(raw))
        self.assertEqual(public["board:eth"]["ok"], True)  # Transport completed.
        self.assertEqual(public["board:eth"]["messages"], ["Unexpected empty source result"])
        self.assertEqual(public["board:crest"]["messages"], ["HTTP 503"])
        self.assertNotIn("secret", json.dumps(public))

    def test_public_status_cannot_be_overridden_by_provider_payload(self) -> None:
        raw = {"board:case": {
            "kind": "board", "items": 0, "ok": False, "errors": 1,
            "status": "successful", "failure_stage": "fetch",
            "messages": ["HTTP 403"],
        }}
        published = public_source_stats(raw)["board:case"]
        self.assertEqual(published["status"], "failed")
        self.assertEqual(published["failure_stage"], "fetch")


if __name__ == "__main__":
    unittest.main()
