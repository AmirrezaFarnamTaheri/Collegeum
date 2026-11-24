# Further core optimization after PR 241

## Result

This change compares against revision **7c410a7d**, which already contains the
earlier MinHash arithmetic optimization. It changes binary conversion only:
complete signatures use the standard-library `struct` encoder/decoder, and an
LSH band batch encodes its signature once before slicing the original byte
ranges. There is no new application cache, signature arithmetic, signature
version, threshold, candidate order or publication-policy change.

On the real 477-record journal, eleven alternating reference/optimized pairs gave:

| Offline workload | Baseline median | Optimized median | Result |
| --- | ---: | ---: | --- |
| Warm ingestion: cached seed, 120 queries, 40 new signature writes | 201.14 ms | 182.26 ms | **9.4% less CPU time** |
| Rebuild index from 477 cached signatures | 25.67 ms | 13.18 ms | **48.7% less CPU time** |
| Cold journal recovery: recompute signatures, then the same queries/writes | 778.90 ms | 779.80 ms | **No measurable change** |

The warm ingestion result improved in nine of eleven pairs; its median paired
improvement was 6.0%. Every cached-index pair improved, with a 50.0% median paired
improvement. Two preceding prototype comparisons also showed approximately
8% lower warm ingestion time. Cold-run differences changed sign between samples
and were small relative to normal timing variation, so no cold speedup or
regression is claimed. The unchanged signature arithmetic dominates that path.

These are local CPU measurements, not whole-pipeline or network latency claims.
The absolute saving in this journal is about 19 ms for warm ingestion and 12.5 ms
for a cached-index rebuild. A fresh CI runner rebuilding every signature from the
journal should not be expected to finish noticeably sooner from this change alone.

The complete raw samples and input/output fingerprints are in
[core-serialization-benchmark.json](core-serialization-benchmark.json).

## Profiling and selection

The current implementation was profiled before changing code. A cold dedupe seed
and 120 mixed queries took approximately 0.83 seconds without profiling. Under
`cProfile`, signature arithmetic consumed 0.751 of 0.851 seconds. The warm replay
revealed another useful cost: decoding persisted signatures took 0.023 seconds,
and constructing band keys took 0.036 seconds, together approximately 24% of the
0.242-second profiled replay. Both operations created or decoded one Python byte
object per 64-bit signature value.

State workloads were also checked using temporary databases, the complete
477-listing journal, and 1,196 seen records:

| Existing state operation | Unprofiled elapsed time |
| --- | ---: |
| Initialize schema and restore listings/seen journals | 86.5 ms |
| Reconcile the same journals into an existing database | 42.6 ms |
| Export the listing journal to a temporary path | 21.1 ms |

Those results did not justify changing recovery transactions, reconciliation or
data validation. All 477 records are inside the configured 120-day dedupe window.
The initial state-profile setup omitted schema initialization and failed before
loading any records; it was corrected to use `db.init` and temporary database
files before measuring these operations. No production database or journal was
written during profiling.

### Attempts kept and rejected

| Attempt | Observation | Decision |
| --- | --- | --- |
| Reduce each base hash modulo the existing prime before the permutation loop | 0.46% cold and 0.72% warm median reduction in seven paired samples | Rejected: below noise |
| Pack/decode in native code, initially packing each band separately | 7.6% warm improvement; no reliable cold improvement | Useful direction; refined to one pack per batch |
| Combine modulo pre-reduction and packed conversion | One comparison appeared faster, but the isolated arithmetic change was not repeatable | Retained conversion only |
| Pack once, then slice the original band byte ranges | Repeated warm improvement and approximately 49% less cached-index rebuild time | Selected |
| Refactor database or state recovery | Small absolute cost and no measured proposal | No change |

Only the selected serialization change is in production code.

## Compatibility and resource behavior

The wire format remains unsigned 64-bit integers in big-endian order. Each band
still hashes the same two-byte band number followed by precisely the same bytes.
The benchmark verifies every journal signature's encoded bytes, decoded values
and band keys before timing. Every replay compares the duplicate listing ID,
matching tier, exact score and newly serialized bytes. Both variants produce
the same 80 duplicate decisions and 40 new signatures.

The implementation retains the former behavior for a partial final word,
noncontiguous or unusual buffer views, out-of-range integers and noninteger
values. Short signatures and values beyond the configured LSH bands have the
same interpretation as before. No stored signature is migrated or discarded.

Packing once temporarily creates the signature's flat byte representation
(1,024 bytes for 128 values) and slices it for each band. Work and temporary space
remain linear in the signature length. No per-record value or computed result is
retained beyond the existing index.

`tests/core/test_minhash_serialization.py` uses only `unittest` and standard-library
modules. It checks golden bytes including unsigned boundaries, multiple lengths
and banding plans, partial blobs, buffer variants, original error classes,
ignored trailing values, LSH candidates and best matches. An operation-count
guard checks one pack per band batch and one unpack per complete signature;
there are no wall-clock test assertions. The earlier frozen MinHash fingerprints
also continue to pass.

## Verification

- The dependency-free core gate passed **470 tests**.
- The dependency-installed core plus identity/recovery regression run passed
  **569 tests and 809 subtests**.
- Ruff passed the changed implementation, regression module and benchmark tool.
- Mypy passed the changed core implementation.
- Repository-wide tests and the standalone distribution rebuild are handled by
  the parent integration review.

## Reproduce offline

```sh
.venv/bin/python tools/benchmark_core_serialization.py --samples 11
PYTHONPATH=src python3 -m unittest discover -s tests/core -t . -q
.venv/bin/python -m pytest tests/core tests/integration/test_identity_regressions.py tests/integration/test_recovery_regressions.py -q
.venv/bin/ruff check src/predoc_pipeline/core/minhash.py tests/core/test_minhash_serialization.py tools/benchmark_core_serialization.py
.venv/bin/mypy src/predoc_pipeline/core/minhash.py
```

The benchmark reads the journal and prints JSON. Every sample starts with a new
index. Cold samples omit persisted signatures and clear permutation coefficients;
warm samples load the same persisted bytes and prewarm the same coefficients.
Variant order alternates. The journal SHA-256 is recorded so different corpora
cannot be compared accidentally. The tool initializes no database, HTTP, model
or delivery clients.
