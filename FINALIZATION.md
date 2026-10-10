# PR #12 implementation and acceptance status — 10 October 2026

The pull-request branch was updated and its CI matrix completed successfully.
Full project acceptance remains open: historical reconciliation and live
provider/source/browser/device checks are not established by offline CI.
No website deployment or real Telegram/X message was performed in this pass.

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
- The dedicated GitHub Actions refresh workflow resolved `uv.lock` from the
  updated project. The runtime no longer depends on vulnerable setuptools:
  the MIT-licensed Twitter text parser is vendored with `importlib.resources`
  replacing `pkg_resources`. CI installs these dependencies on Python 3.11/3.12.
- The single-file distribution includes nested source fixtures, build/verification
  tools, the lockfile, recovery instructions and audit documentation. CI now
  checks manifest freshness and byte-for-byte materialization without dependencies.
  Text is canonicalized to LF so Windows and Linux checkouts produce identical
  manifests; binary fixtures retain their original bytes. Generated dashboard,
  health and RSS outputs are excluded from the reproducible source manifest:
  their publication history is mutable between PR branch and merge checkouts.

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

## Verified CI and release evidence

[CI run 38081644997](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/38081644997)
completed successfully on Python **3.11 and 3.12**, covering:

- **83 dependency-free core tests** before package installation.
- **930 tests and 15 subtests on each Python version**.
- Strict mypy across 63 project source files and Ruff for source, tests and tools.
- Golden-fixture evaluation and offline smoke checks.
- Single-file source freshness and byte-for-byte temporary materialization.
- Actual Hatchling wheel and source archive builds and `verify_release.py` checks
  for required packaged files and exclusion of private/local state.
- Lockfile resolution and artifact regeneration performed by the dedicated
  `refresh-release` workflow before the CI matrix ran.

These are genuine CI observations, not claims of verified external delivery.

Reproduce distribution checks with `python tools/build_single_file.py`,
`python -S tools/verify_single_file.py`, `uv build --offline --out-dir build/release`,
then `python -S tools/verify_release.py`. Archive SHA-256 values are written to
`build/release/verification.json`. Build outputs are local, ignored artifacts.

The old twitter-text `pkg_resources` deprecation and setuptools compatibility
pin have been removed. The vendored MIT implementation and Unicode emoji data
are checked as part of wheel verification. Future Unicode/X-weight updates
remain a maintenance obligation.

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

- New recruitment cohorts, explicit reopening, source-refresh budget rotation
  and complete refreshed-versus-new discovery counters still require work.
  This pass preserves closure and does not automatically reopen a closed row.
- Historical IDs, deduplication decisions, categories, dates, locations and
  feedback associations need a controlled reconciliation with reviewed backups.
  Existing stored outputs were not migrated or regenerated here.
- HTTP cache 304 replay now preserves bodies, conditional requests require a
  replayable body, robots decisions are keyed by origin, and a single 404 no
  longer permanently closes a listing. Pending delivery defers ambiguous 404s
  until independently confirmed after 24 hours. Remaining DNS/public-IP and
  cross-origin redirect constraints need live and adversarial acceptance.
- Telegram uncertain sends are held in `delivery-uncertain` rather than
  automatically replayed. An operator must inspect the destination before using
  `predoc-pipeline telegram-reconcile ID --message-id N`, or
  `predoc-pipeline telegram-reconcile ID --confirmed-not-delivered`.
  Callback replay identifiers are no longer truncated to the latest 500.
  Ambiguous bot-command acknowledgements and real delivery remain to be proven.
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
Passing CI does not close these requirements or certify live publication.
