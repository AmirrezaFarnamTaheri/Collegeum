# Local finalization status — 10 October 2026

The current working tree has been reviewed and the immediate local blockers
repaired. Full project acceptance remains open: the audit includes requirements
that are not established by these local checks. Nothing was pushed, deployed,
or sent to Telegram/X during this work.

## Completed in this finalization pass

- Dependency-requiring identity/quota regressions moved into integration tests.
  The pre-install CI core stage remains genuinely dependency-free.
- Existing encrypted feedback without its original key now raises an explicit
  error, including when a stale plaintext sibling exists. Pipeline execution
  stops before collection instead of exporting an empty personal history.
- Changed adverts can update stored facts through the production duplicate
  path when application identity, title, institution and same-vacancy evidence
  agree. Empty/unknown nullable facts do not erase previous observations.
  Listing identity, feedback hash, delivery history and closure are preserved.
  Refreshes have a separate `RunStats.refreshed` counter.
- Scheduled X single posts now persist submission intent and acknowledgements.
  Restoring the text journal avoids repeating acknowledged requests and blocks
  uncertain requests pending operator reconciliation. Active web listings whose
  X delivery failed are retried separately from website publication, up to
  `X_RETRY_LIMIT` per run. Hidden, closed, expired, excluded and Telegram-routed
  listings are omitted; new attempts are not repeated in the same run.
- Strict mypy passes across all 63 source files and is now required in CI.
  SQLite return types, nullable values, parser attributes and provider output
  contracts are corrected. Missing-import exemptions apply only to named optional
  SDKs/untyped parser libraries; first-party checking remains strict.
- `uv.lock` regenerated from cached package metadata and checked against the
  current project. A network resolution attempt failed because the configured
  proxy was unavailable. Fresh online installation has not been verified.
- The single-file distribution includes nested source fixtures, build/verification
  tools, the lockfile, recovery instructions and audit documentation. CI now
  checks manifest freshness and byte-for-byte materialization without dependencies.
  Text is canonicalized to LF so Windows and Linux checkouts produce identical
  manifests; binary fixtures retain their original bytes.

## Source expansion delivered

The registry has **88 boards: 81 enabled and 7 disabled**, plus two disabled feed
templates and one disabled portal template. These are configured monitor counts,
not independently healthy employers or eligible vacancies.

The completed additions include Nuffield, CREST, ESSEC, Warwick, Bank of Canada,
Sciences Po, Gothenburg, Umeå USBE, Linköping, Duke, Trinity College Cambridge,
Bruegel and Aarhus. NHH remains disabled because its representative Jobbnorge
detail yielded a loading shell. Official-page discovery/detail evidence and
adapter boundaries are recorded in:

- [First expansion](review/2026-10-10/source-expansion.md)
- [Second expansion](review/2026-10-10/source-expansion-batch2.md)
- [Institution investigation](review/2026-10-10/institution-expansion.md)

The latest seven sources yielded 171 discovered adverts/calls, 27 enriched items
and 11 emitted candidates after 16 rejections. These candidates have not been
established as accepted, deduplicated eligible vacancies or published results.

## Local verification

- **83 dependency-free core tests passed**, using Python `-S`.
- **908 tests and 15 subtests passed** after pruning and adding malformed SDK
  response coverage (168.51 seconds).
- Strict mypy passed across all 63 source files; CI now enforces the check.
- Source/test/tool Ruff lint and Git whitespace checks passed.
- Offline smoke passed. Golden-fixture evaluation: 30 cases, 12 true positives,
  18 true negatives, zero false positives/negatives; precision and recall 1.000.
- `uv lock --check --offline` passed (111 resolved packages).
- Single-file manifest and temporary-directory materialization passed with `-S`.
- Offline source archive and wheel builds passed. Archive verification checks
  source fidelity, required distribution files and excluded local/private state.

Reproduce distribution checks with `python tools/build_single_file.py`,
`python -S tools/verify_single_file.py`, `uv build --offline --out-dir build/release`,
then `python -S tools/verify_release.py`. Archive SHA-256 values are written to
`build/release/verification.json`. Build outputs are local, ignored artifacts.

The known twitter-text `pkg_resources` deprecation warning remains. Pinning
setuptools below 81 preserves the parser's present dependency contract.

The cleanup consolidates six source-test modules into two and removes 65 repeated
cases from the 972-case baseline. All institution parser contracts and distinct
invalid-input cases remain; HTTP failures run once per adapter, and shared
registry validation runs directly with separate consumer-wiring checks.
One new case verifies that malformed optional-SDK output consumes its reserved
attempt, records the failure and closes the owned client.
Redundant test-harness counters and derived assertions were removed. Runtime
simplification removes empty publication bookkeeping, repeated routing/coercion
and a custom temporary-directory wrapper. Smoke failures use explicit checks
that remain active under Python `-O`; X reconciliation retains its input guard.

## Remaining acceptance requirements

- Dependency audit reported setuptools 80.10.2 with two duplicate records for
  [GHSA-h35f-9h28-mq5c](https://github.com/advisories/GHSA-h35f-9h28-mq5c).
  The advisory concerns setuptools source-distribution exclusion matching on
  normalization-preserving filesystems; the fix is setuptools 83. The current
  twitter-text parser imports `pkg_resources`, requiring setuptools below 81.
  This project builds with Hatchling and separately verifies archive contents,
  so its current release build does not invoke the affected setuptools path.
  The installed dependency remains flagged; replacing that compatibility
  dependency is still open, and the audit is not reported as clean.
- New recruitment cohorts, explicit reopening, source-refresh budget rotation
  and complete refreshed-versus-new discovery counters still require work.
  This pass preserves closure and does not automatically reopen a closed row.
- Historical IDs, deduplication decisions, categories, dates, locations and
  feedback associations need a controlled reconciliation with reviewed backups.
  Existing stored outputs were not migrated or regenerated here.
- Remaining network/cache/redirect and single-404 closure obligations, uncertain
  Telegram delivery and callback-history retention need requirement-level closure.
- X uncertainty requires verified remote reconciliation. Changed publication
  text fails the journal fingerprint check; changing publication mode/account
  scope starts a separate logical publication. Old unresolved attempts can
  occupy the bounded retry batch until resolved. Remote durable-state persistence
  depends on the workflow's successful commit/push.
- Representative live coverage across the entire registry, current application
  availability, provider behavior, workflow scheduling/quotas, narrow-mobile UI,
  hosted Pages and actual Telegram/X delivery have not been accepted by this pass.

The detailed outstanding audit remains in
[the remediation ledger](review/2026-10-05/remediation-ledger.md) and
[the dated remaining-work inventory](review/2026-10-05/remaining-work.md).
Passing local checks do not close these requirements.
