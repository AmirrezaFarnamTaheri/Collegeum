"""Compare the original and current MinHash kernels without network or writes.

Run after installing the project: python tools/benchmark_core_dedupe.py
Uses the real journal's identity fields, never delivery credentials or clients.
The reference kernel preserves the implementation before the 2026-11-24
optimization so the same corpus can be compared in one process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

from predoc_pipeline.core import minhash
from predoc_pipeline.core.dedupe import Deduplicator
from predoc_pipeline.core.minhash import _MAX, _PRIME, MinHash, _base_hash, _perms

ROOT = Path(__file__).resolve().parents[1]


def reference_kernel(cls, tokens, num_perm=128):
    """Original token-first arithmetic; identical coefficients and output type."""
    a_vals, b_vals = _perms(num_perm)
    values = [_MAX] * num_perm
    seen = False
    for token in tokens:
        seen = True
        hashed = _base_hash(token)
        for index in range(num_perm):
            value = (a_vals[index] * hashed + b_vals[index]) % _PRIME
            if value < values[index]:
                values[index] = value
    return cls(tuple(values)) if seen else None


def corpus(path):
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    queries = []
    count = min(120, len(rows))
    for index in range(count):
        row = rows[index * len(rows) // count]
        query = {
            "text": Deduplicator.text_for(row["title"], row["summary"]),
            "institution": row["institution"], "title": row["title"],
            "principal_investigator": row.get("principal_investigator"),
            "deadline": row.get("deadline"),
        }
        if index % 3 == 1:
            query["text"] += " Applicants also support empirical analysis and research projects."
        elif index % 3 == 2:
            query["institution"] += f" Independent Hiring Unit {index}"
            query["title"] = f"Independent Research Vacancy {index}"
        queries.append(query)
    return raw, rows, queries


def replay(rows, queries):
    deduper = Deduplicator()
    deduper.seed(rows)
    outcomes = []
    for query in queries:
        match = deduper.find(**query)
        outcomes.append((match.listing_id, match.tier, match.score) if match else None)
    return outcomes


def run(path, samples):
    raw, rows, queries = corpus(path)
    implementation = MinHash.__dict__["from_tokens"]
    kernels = {"reference": classmethod(reference_kernel), "optimized": implementation}
    warm_rows = [dict(row) for row in rows]
    signature_digest = hashlib.sha256()
    for row in warm_rows:
        text = Deduplicator.text_for(row["title"], row["summary"])
        try:
            MinHash.from_tokens = kernels["reference"]
            expected = Deduplicator.signature(text)
        finally:
            MinHash.from_tokens = implementation
        actual = Deduplicator.signature(text)
        if actual != expected:
            raise AssertionError(f"Signature changed for listing {row['id']}")
        blob = actual.to_bytes() if actual else None
        row["signature"] = blob
        signature_digest.update(blob or b"")
    results = {}
    try:
        for mode, entries in (("cold_recovery", rows), ("warm_persisted_signatures", warm_rows)):
            timings = {name: [] for name in kernels}
            expected_outcomes = None
            for sample in range(samples):
                # Alternate paired order; explicitly reset coefficient cache
                # for each cold run, and prewarm it for each warm run.
                names = list(kernels) if sample % 2 == 0 else list(reversed(kernels))
                for name in names:
                    MinHash.from_tokens = kernels[name]
                    minhash._PERM_CACHE.clear()
                    if mode == "warm_persisted_signatures":
                        minhash._perms(128)
                    started = time.perf_counter()
                    outcomes = replay(entries, queries)
                    timings[name].append(time.perf_counter() - started)
                    if expected_outcomes is None:
                        expected_outcomes = outcomes
                    elif outcomes != expected_outcomes:
                        raise AssertionError("Duplicate identity, tier or score changed")
            medians = {name: statistics.median(values) for name, values in timings.items()}
            results[mode] = {
                "seconds": timings, "median_seconds": medians,
                "speedup": medians["reference"] / medians["optimized"],
                "reduction_percent": 100 * (1 - medians["optimized"] / medians["reference"]),
                "matched_queries": sum(result is not None for result in expected_outcomes),
                "outcomes_sha256": hashlib.sha256(
                    json.dumps(expected_outcomes, separators=(",", ":")).encode(),
                ).hexdigest(),
            }
    finally:
        MinHash.from_tokens = implementation
    return {
        "python": platform.python_version(), "platform": platform.platform(),
        "journal_sha256": hashlib.sha256(raw).hexdigest(),
        "corpus_records": len(rows), "queries": len(queries), "samples": samples,
        "query_mix": "equal exact mirrors, altered descriptions and unrelated employers",
        "all_signature_bytes_identical": True,
        "signatures_sha256": signature_digest.hexdigest(), "workloads": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, default=ROOT / "data/listings.ndjson")
    parser.add_argument("--samples", type=int, default=7)
    args = parser.parse_args()
    if args.samples < 3:
        parser.error("Use at least three repeated samples")
    print(json.dumps(run(args.journal, args.samples), indent=2))


if __name__ == "__main__":
    main()
