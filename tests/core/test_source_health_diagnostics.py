"""Regression tests for actionable, non-sensitive public source health."""
from __future__ import annotations

import json
import unittest

from predoc_pipeline.core.health import public_failure, public_source_stats


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


if __name__ == "__main__":
    unittest.main()
