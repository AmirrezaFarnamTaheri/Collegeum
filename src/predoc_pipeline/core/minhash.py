"""MinHash signatures and banded LSH. Stdlib only.

Replaces ``datasketch``, which pulls in numpy for roughly ninety lines of
arithmetic. On a cold CI runner that dependency costs more wall-clock time than
the entire deduplication stage it serves.

Math
----
For sets A and B with Jaccard similarity s, and a random permutation h of the
universe, P[min h(A) = min h(B)] = s. Averaging over ``num_perm`` independent
permutations gives an unbiased estimator of s with standard error about
1/sqrt(num_perm); at num_perm=128 that is roughly 0.088. The threshold is
therefore compared against an *estimate*, never trusted as exact -- which is
precisely why a third, deterministic tier exists downstream.

Banded LSH splits the signature into b bands of r rows (b * r = num_perm). Two
items become candidates iff at least one band matches exactly:

    P(candidate | s) = 1 - (1 - s**r)**b

``_choose_bands`` picks (b, r) minimising the integrated probability of error
either side of the target threshold -- the standard optimisation, and the same
criterion datasketch applies.

Permutation coefficients come from a fixed seed, so a signature computed today
is comparable with one persisted months ago. Changing ``_SEED`` or ``_PRIME``
invalidates every stored signature: bump ``SIGNATURE_VERSION`` if you do, and
the loader will discard stale blobs instead of comparing nonsense.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["MinHash", "MinHashLSH", "SIGNATURE_VERSION", "jaccard"]

SIGNATURE_VERSION = 1

# Mersenne prime 2^61 - 1: collisions are negligible and (a*x + b) % PRIME
# stays comfortably inside CPython's fast integer path.
_PRIME = (1 << 61) - 1
_MAX = _PRIME - 1
_SEED = 0x5EED1DEA


def _permutations(num_perm: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Deterministic (a, b) coefficients for ``num_perm`` hash functions."""
    a_vals: list[int] = []
    b_vals: list[int] = []
    for i in range(num_perm):
        digest = hashlib.blake2b(
            i.to_bytes(4, "big"), digest_size=16, key=_SEED.to_bytes(8, "big")
        ).digest()
        a_vals.append(int.from_bytes(digest[:8], "big") % (_PRIME - 1) + 1)  # a != 0
        b_vals.append(int.from_bytes(digest[8:], "big") % _PRIME)
    return tuple(a_vals), tuple(b_vals)


_PERM_CACHE: dict[int, tuple[tuple[int, ...], tuple[int, ...]]] = {}


def _perms(num_perm: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    if num_perm not in _PERM_CACHE:
        _PERM_CACHE[num_perm] = _permutations(num_perm)
    return _PERM_CACHE[num_perm]


def _base_hash(token: str) -> int:
    return int.from_bytes(
        hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big"
    )


@dataclass(frozen=True, slots=True)
class MinHash:
    """An immutable MinHash signature over a set of string shingles."""

    values: tuple[int, ...]

    @classmethod
    def from_tokens(cls, tokens: Iterable[str], num_perm: int = 128) -> MinHash | None:
        """Build a signature, or None when there is nothing to hash.

        Returning None for an empty token set is load-bearing. Two all-max
        signatures have Jaccard 1.0, so empty-versus-empty would otherwise
        report a perfect duplicate and silently suppress every short listing.
        """
        a_vals, b_vals = _perms(num_perm)
        signature = [_MAX] * num_perm
        seen = False
        for token in tokens:
            seen = True
            h = _base_hash(token)
            for i in range(num_perm):
                value = (a_vals[i] * h + b_vals[i]) % _PRIME
                if value < signature[i]:
                    signature[i] = value
        return cls(tuple(signature)) if seen else None

    def jaccard(self, other: MinHash) -> float:
        if len(self.values) != len(other.values):
            raise ValueError("signature lengths differ")
        matches = sum(1 for x, y in zip(self.values, other.values, strict=False) if x == y)
        return matches / len(self.values)

    def to_bytes(self) -> bytes:
        return b"".join(v.to_bytes(8, "big") for v in self.values)

    @classmethod
    def from_bytes(cls, blob: bytes) -> MinHash:
        return cls(
            tuple(int.from_bytes(blob[i : i + 8], "big") for i in range(0, len(blob), 8))
        )


def jaccard(a: set[str], b: set[str]) -> float:
    """Exact Jaccard. Used in tests to check the estimator's calibration."""
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _false_positive_area(threshold: float, b: int, r: int, steps: int = 200) -> float:
    """Integral of P(candidate | s) for s below the threshold."""
    total = 0.0
    width = threshold / steps
    for i in range(steps):
        s = (i + 0.5) * width
        total += (1.0 - (1.0 - s**r) ** b) * width
    return total


def _false_negative_area(threshold: float, b: int, r: int, steps: int = 200) -> float:
    """Integral of 1 - P(candidate | s) for s above the threshold."""
    total = 0.0
    width = (1.0 - threshold) / steps
    for i in range(steps):
        s = threshold + (i + 0.5) * width
        total += (1.0 - (1.0 - (1.0 - s**r) ** b)) * width
    return total


def _choose_bands(threshold: float, num_perm: int, fp_weight: float = 0.5) -> tuple[int, int]:
    """Pick (bands, rows) minimising weighted error around ``threshold``."""
    best = (num_perm, 1)
    best_error = float("inf")
    for bands in range(1, num_perm + 1):
        if num_perm % bands:
            continue
        rows = num_perm // bands
        error = fp_weight * _false_positive_area(threshold, bands, rows) + (
            1.0 - fp_weight
        ) * _false_negative_area(threshold, bands, rows)
        if error < best_error:
            best_error, best = error, (bands, rows)
    return best


class MinHashLSH:
    """In-memory banded LSH index keyed by integer listing ids."""

    def __init__(self, threshold: float = 0.85, num_perm: int = 128) -> None:
        if not 0.0 < threshold <= 1.0:
            raise ValueError("threshold must be in (0, 1]")
        self.threshold = threshold
        self.num_perm = num_perm
        self.bands, self.rows = _choose_bands(threshold, num_perm)
        self._buckets: list[dict[bytes, list[int]]] = [{} for _ in range(self.bands)]
        self._signatures: dict[int, MinHash] = {}

    def __len__(self) -> int:
        return len(self._signatures)

    def _band_keys(self, signature: MinHash) -> list[bytes]:
        keys = []
        for band in range(self.bands):
            chunk = signature.values[band * self.rows : (band + 1) * self.rows]
            payload = band.to_bytes(2, "big") + b"".join(v.to_bytes(8, "big") for v in chunk)
            keys.append(hashlib.blake2b(payload, digest_size=16).digest())
        return keys

    def insert(self, key: int, signature: MinHash) -> None:
        if key in self._signatures:
            return
        self._signatures[key] = signature
        for band, band_key in enumerate(self._band_keys(signature)):
            self._buckets[band].setdefault(band_key, []).append(key)

    def query(self, signature: MinHash) -> set[int]:
        """Candidate keys sharing at least one band with ``signature``."""
        out: set[int] = set()
        for band, band_key in enumerate(self._band_keys(signature)):
            out.update(self._buckets[band].get(band_key, ()))
        return out

    def best_match(self, signature: MinHash) -> tuple[int | None, float]:
        """Highest-similarity candidate and its estimated Jaccard."""
        best_key, best_score = None, 0.0
        for key in self.query(signature):
            score = signature.jaccard(self._signatures[key])
            if score > best_score:
                best_key, best_score = key, score
        return best_key, best_score

    def probability(self, similarity: float) -> float:
        """P(candidate | similarity) for this index's banding. For docs and tests."""
        return 1.0 - (1.0 - similarity**self.rows) ** self.bands

    def signature(self, key: int) -> MinHash | None:
        return self._signatures.get(key)
