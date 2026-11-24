"""Offline replay of MinHash binary conversion against the PR 241 implementation.

The reference methods are from revision 7c410a7d. Signature arithmetic is the
current optimized implementation in both variants; this does not compare against
the older token-first kernel. Reads a local journal and prints JSON, with no
database, network, credentials or delivery clients.
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
from predoc_pipeline.core.minhash import MinHash, MinHashLSH

ROOT = Path(__file__).resolve().parents[1]


def reference_to_bytes(self):
    return b"".join(value.to_bytes(8, "big") for value in self.values)


def reference_from_bytes(cls, blob):
    return cls(tuple(int.from_bytes(blob[index:index + 8], "big")
                     for index in range(0, len(blob), 8)))


def reference_band_keys(self, signature):
    keys = []
    for band in range(self.bands):
        chunk = signature.values[band * self.rows:(band + 1) * self.rows]
        payload = band.to_bytes(2, "big") + b"".join(value.to_bytes(8, "big") for value in chunk)
        keys.append(hashlib.blake2b(payload, digest_size=16).digest())
    return keys


def corpus(path):
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if not rows:
        raise ValueError("The benchmark needs at least one journal record")
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


def verified_warm_rows(rows):
    entries = []
    signatures = hashlib.sha256()
    bands = hashlib.sha256()
    index = MinHashLSH(threshold=0.82)
    for row in rows:
        signature = Deduplicator.signature(Deduplicator.text_for(row["title"], row["summary"]))
        blob = signature.to_bytes() if signature is not None else None
        if signature is not None:
            if blob != reference_to_bytes(signature):
                raise AssertionError("Persisted signature bytes changed")
            if MinHash.from_bytes(blob) != reference_from_bytes(MinHash, blob):
                raise AssertionError("Stored signature decoding changed")
            actual_bands = index._band_keys(signature)
            if actual_bands != reference_band_keys(index, signature):
                raise AssertionError("LSH bucket identity changed")
            bands.update(b"".join(actual_bands))
        signatures.update(blob or b"")
        entries.append({**row, "signature": blob})
    return entries, signatures.hexdigest(), bands.hexdigest()


def replay(rows, queries):
    deduper = Deduplicator()
    deduper.seed(rows)
    next_id = max(row["id"] for row in rows) + 1
    outcomes, persisted = [], []
    for query in queries:
        # Match the live ingestion path: compute once, pass to find/add, and
        # serialize only newly accepted identities for durable storage.
        signature = deduper.signature(query["text"])
        duplicate = deduper.find(**query, signature=signature)
        outcomes.append((duplicate.listing_id, duplicate.tier, duplicate.score)
                        if duplicate else None)
        if duplicate is None:
            deduper.add(next_id, **query, signature=signature)
            next_id += 1
            persisted.append(signature.to_bytes() if signature is not None else b"")
    return outcomes, persisted


def run(path, samples):
    raw, rows, queries = corpus(path)
    warm_rows, signature_digest, band_digest = verified_warm_rows(rows)
    current = {name: MinHash.__dict__[name] for name in ("to_bytes", "from_bytes")}
    current_bands = MinHashLSH._band_keys

    def install(name):
        MinHash.to_bytes = reference_to_bytes if name == "reference" else current["to_bytes"]
        MinHash.from_bytes = (classmethod(reference_from_bytes) if name == "reference"
                              else current["from_bytes"])
        MinHashLSH._band_keys = reference_band_keys if name == "reference" else current_bands

    results = {}
    try:
        for mode, entries, query_batch in (
            ("cold_journal_recovery", rows, queries),
            ("warm_ingestion", warm_rows, queries),
            ("cached_index_rebuild", warm_rows, []),
        ):
            timings = {"reference": [], "optimized": []}
            expected = None
            for sample in range(samples):
                names = ("reference", "optimized")
                if sample % 2:
                    names = tuple(reversed(names))
                for name in names:
                    install(name)
                    minhash._PERM_CACHE.clear()
                    if mode != "cold_journal_recovery":
                        minhash._perms(128)
                    started = time.perf_counter()
                    outcome = replay(entries, query_batch)
                    timings[name].append(time.perf_counter() - started)
                    if expected is None:
                        expected = outcome
                    elif outcome != expected:
                        raise AssertionError("Duplicate outcome or newly stored bytes changed")
            medians = {name: statistics.median(values) for name, values in timings.items()}
            paired = [100 * (1 - after / before) for before, after in zip(
                timings["reference"], timings["optimized"], strict=True,
            )]
            digest = hashlib.sha256(json.dumps(expected[0], separators=(",", ":")).encode())
            digest.update(b"".join(expected[1]))
            results[mode] = {
                "seconds": timings, "median_seconds": medians,
                "reduction_percent": 100 * (1 - medians["optimized"] / medians["reference"]),
                "median_paired_reduction_percent": statistics.median(paired),
                "improved_pairs": sum(value > 0 for value in paired),
                "matched_queries": sum(item is not None for item in expected[0]),
                "new_signatures_written": len(expected[1]),
                "outcomes_and_writes_sha256": digest.hexdigest(),
            }
    finally:
        install("optimized")
    return {
        "baseline_revision": "7c410a7d", "python": platform.python_version(),
        "platform": platform.platform(), "samples_per_variant": samples,
        "journal_sha256": hashlib.sha256(raw).hexdigest(),
        "corpus_records": len(rows), "queries": len(queries),
        "query_mix": "cycling exact mirrors, altered descriptions and unrelated employers",
        "signature_arithmetic_changed": False,
        "all_signature_bytes_and_band_keys_identical": True,
        "signatures_sha256": signature_digest, "band_keys_sha256": band_digest,
        "workloads": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, default=ROOT / "data/listings.ndjson")
    parser.add_argument("--samples", type=int, default=11)
    args = parser.parse_args()
    if args.samples < 3:
        parser.error("Use at least three repeated samples")
    print(json.dumps(run(args.journal, args.samples), indent=2))


if __name__ == "__main__":
    main()
