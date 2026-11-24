"""Binary compatibility and bounded conversion work for stored MinHash values."""

from __future__ import annotations

import hashlib
import random
import unittest
from array import array
from unittest.mock import patch

from predoc_pipeline.core import minhash
from predoc_pipeline.core.minhash import MinHash, MinHashLSH


def legacy_bytes(values):
    return b"".join(value.to_bytes(8, "big") for value in values)


def legacy_values(blob):
    return tuple(int.from_bytes(blob[index:index + 8], "big") for index in range(0, len(blob), 8))


def legacy_band_keys(index, signature):
    keys = []
    for band in range(index.bands):
        chunk = signature.values[band * index.rows:(band + 1) * index.rows]
        payload = band.to_bytes(2, "big") + legacy_bytes(chunk)
        keys.append(hashlib.blake2b(payload, digest_size=16).digest())
    return keys


class MinHashSerializationTests(unittest.TestCase):
    def test_unsigned_big_endian_wire_format_is_unchanged(self):
        values = (0, 1, 2**32, 2**61 - 1, 2**64 - 1)
        expected = bytes.fromhex(
            "0000000000000000 0000000000000001 0000000100000000 "
            "1fffffffffffffff ffffffffffffffff"
        )
        self.assertEqual(MinHash(values).to_bytes(), expected)
        self.assertEqual(MinHash.from_bytes(expected).values, values)
        self.assertEqual(minhash.SIGNATURE_VERSION, 1)

    def test_complete_signatures_match_original_encoder_and_decoder(self):
        rng = random.Random(4107)
        for count in (0, 1, 3, 8, 16, 32, 64, 128, 256):
            with self.subTest(count=count):
                values = tuple(rng.randrange(2**64) for _ in range(count))
                signature = MinHash(values)
                expected = legacy_bytes(values)
                self.assertEqual(signature.to_bytes(), expected)
                self.assertEqual(MinHash.from_bytes(expected), signature)

    def test_partial_final_words_keep_legacy_seed_loader_behavior(self):
        data = bytes(range(256)) * 5
        for length in (*range(18), 63, 65, 1023, 1025):
            with self.subTest(length=length):
                blob = data[:length]
                self.assertEqual(MinHash.from_bytes(blob).values, legacy_values(blob))

    def test_buffer_inputs_retain_original_interpretation(self):
        source = bytes(range(128))
        cases = [source, bytearray(source), memoryview(source), memoryview(source)[::2],
                 memoryview(array("Q", range(16)))]
        for blob in cases:
            with self.subTest(type=type(blob).__name__, length=len(blob)):
                self.assertEqual(MinHash.from_bytes(blob).values, legacy_values(blob))

    def test_invalid_values_keep_original_errors_without_truncation(self):
        for value in (-1, 2**64, None, 1.5, "1"):
            with self.subTest(value=value):
                try:
                    legacy_bytes((value,))
                except (OverflowError, TypeError, AttributeError) as exc:
                    expected_error = type(exc)
                else:
                    self.fail("The legacy encoder unexpectedly accepted the invalid value")
                with self.assertRaises(expected_error):
                    MinHash((value,)).to_bytes()

    def test_band_hashes_match_for_multiple_banding_plans_and_lengths(self):
        for num_perm, threshold in ((8, 0.5), (64, 0.85), (128, 0.82), (256, 0.9)):
            index = MinHashLSH(threshold, num_perm)
            for count in (0, 1, index.rows - 1, index.rows, index.rows + 1,
                          num_perm - 1, num_perm, num_perm + 1):
                with self.subTest(num_perm=num_perm, threshold=threshold, count=count):
                    signature = MinHash(tuple(n * n + 17 for n in range(max(0, count))))
                    self.assertEqual(
                        index._band_keys(signature), legacy_band_keys(index, signature),
                    )

    def test_values_beyond_configured_bands_remain_ignored(self):
        index = MinHashLSH(0.82, 128)
        signature = MinHash((*range(128), -1))
        self.assertEqual(index._band_keys(signature), legacy_band_keys(index, signature))

    def test_lsh_candidates_and_best_match_are_identical(self):
        signatures = [
            MinHash.from_tokens([
                f"research-shingle-{number}" for number in range(start, start + 60)
            ])
            for start in (0, 1, 2, 30, 100)
        ]
        current = MinHashLSH(0.82, 128)
        reference = MinHashLSH(0.82, 128)
        for key, signature in enumerate(signatures):
            current.insert(key, signature)
            with patch.object(MinHashLSH, "_band_keys", legacy_band_keys):
                reference.insert(key, signature)
        self.assertEqual(current._buckets, reference._buckets)
        for signature in signatures:
            candidates, best = current.query(signature), current.best_match(signature)
            with patch.object(MinHashLSH, "_band_keys", legacy_band_keys):
                self.assertEqual(candidates, reference.query(signature))
                self.assertEqual(best, reference.best_match(signature))

    def test_band_batch_uses_one_pack_and_decode_uses_one_unpack(self):
        signature = MinHash(tuple(range(128)))
        index = MinHashLSH(0.82, 128)
        with patch.object(minhash.struct, "pack", wraps=minhash.struct.pack) as packed:
            keys = index._band_keys(signature)
        self.assertEqual(len(keys), index.bands)
        self.assertEqual(packed.call_count, 1)
        with patch.object(minhash.struct, "unpack", wraps=minhash.struct.unpack) as unpacked:
            self.assertEqual(MinHash.from_bytes(legacy_bytes(signature.values)), signature)
        self.assertEqual(unpacked.call_count, 1)


if __name__ == "__main__":
    unittest.main()
