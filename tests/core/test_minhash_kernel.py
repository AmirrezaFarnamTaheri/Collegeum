"""Persisted-signature compatibility and single-pass input regressions."""

from __future__ import annotations

import hashlib
import random
import unittest
from unittest.mock import patch

from predoc_pipeline.core import minhash
from predoc_pipeline.core.minhash import MinHash


def reference_values(tokens, num_perm):
    """The original token-first kernel, retained as a compatibility oracle."""
    a_vals, b_vals = minhash._perms(num_perm)
    values = [minhash._MAX] * num_perm
    seen = False
    for token in tokens:
        seen = True
        hashed = minhash._base_hash(token)
        for index in range(num_perm):
            value = (a_vals[index] * hashed + b_vals[index]) % minhash._PRIME
            if value < values[index]:
                values[index] = value
    return tuple(values) if seen else None


class MinHashKernelTests(unittest.TestCase):
    def test_version_one_signature_bytes_are_unchanged(self):
        cases = [
            (["alpha", "beta", "gamma"], 8,
             "b50d44946bb98dcc01c98af3b25ff5fbfd6ae97567e394f1cde268ef0a4e17d9"),
            (["Café", "cafe\u0301", "東京", "München", "🧪 research", "", "alpha beta"], 128,
             "eb5ce4b2143682619872c478203584b4ff40797ccbf672b0e2d0bd2c3ef68e2d"),
            ([f"research-token-{i:04d}" for i in range(1024)], 128,
             "a0d9f04c48770ea14d6c2ed7a02f3021fc12097f1b0f4b9650fa897a6c10bc7e"),
        ]
        for tokens, num_perm, digest in cases:
            with self.subTest(tokens=len(tokens), num_perm=num_perm):
                signature = MinHash.from_tokens(iter(tokens), num_perm)
                self.assertIsNotNone(signature)
                self.assertEqual(hashlib.sha256(signature.to_bytes()).hexdigest(), digest)
                self.assertEqual(MinHash.from_bytes(signature.to_bytes()), signature)

    def test_permutation_first_kernel_matches_token_first_reference(self):
        for num_perm in (1, 8, 32, 64, 128):
            rng = random.Random(31027)
            for count in (0, 1, 3, 24, 128):
                with self.subTest(num_perm=num_perm, tokens=count):
                    tokens = [f"shingle-{rng.randrange(250)}-é" for _ in range(count)]
                    expected = reference_values(tokens, num_perm)
                    actual = MinHash.from_tokens(iter(tokens), num_perm)
                    self.assertEqual(actual.values if actual is not None else None, expected)

    def test_empty_iterators_remain_unindexable_and_are_not_perfect_duplicates(self):
        self.assertIsNone(MinHash.from_tokens(iter(())))
        self.assertIsNone(MinHash.from_tokens(value for value in []))

    def test_each_token_is_consumed_and_hashed_once_not_once_per_permutation(self):
        tokens = ["alpha beta", "café", "東京"]
        consumed = []

        def once():
            for token in tokens:
                consumed.append(token)
                yield token

        with patch.object(minhash, "_base_hash", wraps=minhash._base_hash) as base_hash:
            signature = MinHash.from_tokens(once(), num_perm=128)
        self.assertEqual(consumed, tokens)
        self.assertEqual(base_hash.call_count, len(tokens))
        self.assertIsNotNone(signature)
        self.assertEqual(signature.values, reference_values(tokens, 128))

    def test_hash_extremes_preserve_exact_integer_modulo_arithmetic(self):
        tokens = ["zero", "prime", "largest", "maximum-64-bit"]
        hashes = dict(zip(
            tokens, (0, minhash._PRIME, minhash._PRIME - 1, (1 << 64) - 1), strict=True,
        ))
        with patch.object(minhash, "_base_hash", side_effect=hashes.__getitem__):
            signature = MinHash.from_tokens(tokens)
            expected = reference_values(tokens, 128)
        self.assertIsNotNone(signature)
        self.assertEqual(signature.values, expected)

    def test_token_order_and_repetition_do_not_change_set_identity(self):
        signature = MinHash.from_tokens(["alpha", "beta", "gamma"])
        self.assertEqual(signature, MinHash.from_tokens(["gamma", "alpha", "beta", "alpha"]))


if __name__ == "__main__":
    unittest.main()
