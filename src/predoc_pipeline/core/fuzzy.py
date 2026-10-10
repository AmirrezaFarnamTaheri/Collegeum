"""Token-sort edit-distance ratio.

Uses rapidfuzz when it is installed (a small wheel with no transitive deps) and
falls back to an equivalent pure-Python implementation otherwise, so the fuzzy
deduplication tier degrades in speed rather than disappearing. Both paths share
the same normalisation, and the tests assert they agree on a fixture set.
"""

from __future__ import annotations

from types import ModuleType

_rf: ModuleType | None

__all__ = ["token_sort_ratio", "ratio", "BACKEND"]

try:  # pragma: no cover - depends on environment
    from rapidfuzz import fuzz as _rf

    BACKEND = "rapidfuzz"
except Exception:  # pragma: no cover
    _rf = None
    BACKEND = "stdlib"


def _levenshtein(a: str, b: str) -> int:
    """Two-row dynamic program. O(len(a)*len(b)) time, O(len(b)) space."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,               # deletion
                    current[j - 1] + 1,            # insertion
                    previous[j - 1] + (ca != cb),  # substitution
                )
            )
        previous = current
    return previous[-1]


def ratio(a: str, b: str) -> float:
    """Normalised similarity in [0, 100]."""
    if _rf is not None:
        return float(_rf.ratio(a, b))
    if not a and not b:
        return 100.0
    longest = max(len(a), len(b))
    if longest == 0:
        return 100.0
    return max(0.0, (1.0 - _levenshtein(a, b) / longest) * 100.0)


def token_sort_ratio(a: str, b: str) -> float:
    """Similarity after sorting whitespace-separated tokens in each string."""
    if _rf is not None:
        return float(_rf.token_sort_ratio(a, b))
    sa = " ".join(sorted((a or "").split()))
    sb = " ".join(sorted((b or "").split()))
    return ratio(sa, sb)
