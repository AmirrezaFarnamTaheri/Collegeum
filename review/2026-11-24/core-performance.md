# Core deduplication performance review — 24 November 2026

## Result and scope

The MinHash arithmetic loop now processes one permutation at a time, keeping its
coefficients and current minimum in local variables. The original implementation
repeated three list lookups for every shingle/permutation pair. Each token is still
hashed exactly once, and every multiplication, addition and modulo operation uses
the original coefficients and prime. Persisted signature bytes, signature version,
LSH thresholds, candidate ordering and duplicate decisions are unchanged.

An offline replay of the repository's 477-record journal and 120 mixed incoming
queries improved both measured paths:

| Workload | Original median | Optimized median | Time reduction |
| --- | ---: | ---: | ---: |
| Cold recovery: rebuild signatures, seed index, query | 1.0059 s | 0.8849 s | 12.0% |
| Warm state: load persisted signatures, seed index, query | 0.2249 s | 0.2005 s | 10.8% |

These are nine alternating reference/optimized pairs per workload on Python
3.12.14. They measure CPU work on local data; they do not estimate network,
collection, model inference or delivery latency. The raw samples, environment and
corpus fingerprints are in [core-dedupe-benchmark.json](core-dedupe-benchmark.json).
All nine cold samples improved, and eight of nine warm pairs improved. Warm
measurements have visible scheduling noise, so the median is reported rather than
the fastest run.

## Why this change

Before editing, profiling a journal seed followed by 477 exact-mirror queries took
1.488 seconds under `cProfile` (1.466 seconds without the profiler).
`MinHash.from_tokens` accounted for 1.321 seconds of cumulative time, approximately
89% of the profiled workload. Its 51,394 base-hash calls took only 0.063 seconds;
most time was in the repeated arithmetic loop. Institution normalization took
approximately 0.011 seconds and was not a useful optimization target.

Three loop variants were compared on the same 477 signature inputs, five times
each. Every variant produced the same bytes:

| Attempt | Median kernel time | Decision |
| --- | ---: | --- |
| Original token-first loop | 0.6164 s | Baseline |
| Transposed loop with generator and `min` | 0.5870 s | Slower than selected variant |
| Transposed loop with list comprehension and `min` | 0.6133 s | No convincing improvement; rejected |
| Transposed loop with explicit local minimum | 0.5567 s | Selected; approximately 9.7% reduction |

Only the selected variant is in production code. A first version of the replay
reference used a module attribute lookup where the old kernel used a module
global. That comparison was discarded, the reference was corrected to mirror the
old lookup pattern, and every final sample was rerun. The committed JSON contains
only the corrected comparison.

## Correctness and resource tradeoff

The benchmark compares all 477 persisted signatures byte for byte before timing.
It compares every query's matched listing ID, match tier and exact score on every
run. The query set contains 40 exact mirrors, 40 descriptions with an added
sentence, and 40 unrelated employer/title combinations. Both kernels find the
same 80 matches. Cold runs clear the coefficient cache; warm runs load persisted
signature blobs and prewarm the same coefficients. Each sample creates a fresh
index, and comparison order alternates to limit ordering bias.

The new loop temporarily retains one 64-bit Python integer per input token. Input
iteration remains single-pass, and no cross-record or unbounded process cache is
introduced. A separate `tracemalloc` check with warmed coefficient cache found:

| Signature input | Original peak | Optimized peak |
| --- | ---: | ---: |
| Largest journal description, 99 word shingles | 7,272 bytes | 11,680 bytes |
| Large regression input, 1,024 tokens | 7,272 bytes | 52,364 bytes |

This changes temporary memory from approximately O(permutations) to
O(permutations + tokens). It is a small cost for the bounded descriptions used by
this pipeline. Arbitrarily large external callers should account for it; no
input truncation was introduced because that would change signatures.

`tests/core/test_minhash_kernel.py` checks frozen signature fingerprints, a direct
copy of the old arithmetic across deterministic random inputs and permutation
counts, empty inputs, Unicode, duplicates/order independence, extreme base hash
values, a 1,024-token input and byte round trips. A generator/instrumentation test
guards the one-pass, one-base-hash-per-token work bound without relying on flaky
wall-clock assertions.

The initial focused core, identity and recovery regression run passed 142 tests
and 21 subtests. The new regression module now uses only `unittest` and standard
library imports, preserving the dependency-free first CI gate; its parameterized
inputs run as 28 subtests. The final standard-library core gate passed **461
tests** with `PYTHONPATH=src python3 -m unittest discover -s tests/core -t . -q`.
Lint passed for the kernel, regression test and benchmark tool. The complete
dependency-installed suite and distribution rebuild remain part of the parent
review.

## Reproduce without network or mutation

```sh
.venv/bin/python tools/benchmark_core_dedupe.py --samples 9
PYTHONPATH=src python3 -m unittest discover -s tests/core -t . -q
.venv/bin/python -m pytest tests/core/test_minhash_kernel.py tests/core/test_core.py tests/integration/test_identity_regressions.py tests/integration/test_recovery_regressions.py -q
.venv/bin/ruff check src/predoc_pipeline/core/minhash.py tests/core/test_minhash_kernel.py tools/benchmark_core_dedupe.py
```

The benchmark reads the journal and writes JSON to standard output. It does not
initialize collectors, databases, credentials, HTTP clients or publishers. Use
`--journal` to compare another local journal; the output records its SHA-256 so
results from different datasets cannot be confused.
