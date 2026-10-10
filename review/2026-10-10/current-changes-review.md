# Current working-tree review — 10 October 2026

**Finalization follow-up:** The two P1 findings below have been repaired locally.
Same-vacancy fact refresh now has a production caller, and scheduled single posts
use the durable X journal with bounded independent retries. The original findings
remain here as review evidence. See [FINALIZATION.md](../../FINALIZATION.md) for
current verification and the outstanding acceptance requirements.

Reviewed the uncommitted changes relative to HEAD, including the added identity,
quota, health, registry and X recovery modules and regression tests. This is a
local review; it does not certify deployment, historical data repair, live model
providers, or Telegram/X delivery. Existing edits were preserved. This pass adds
only source configuration, source fixtures/tests and this review record.

## Blocking findings

### P1 — The dependency-free CI stage fails before installation

`.github/workflows/ci.yml:28` runs `unittest discover -s tests/core -t .` before
installing dependencies. The newly added `tests/core/test_identity_regressions.py:5`
imports pytest and then board code; `tests/core/test_quota_regressions.py:11`
imports httpx/pytest and the extraction provider. Discovery imports both files,
even though they contain pytest functions rather than unittest cases.

Reproduced with Python's `-S` option and the same unittest discovery loader:
two `_FailedTest` modules, reporting missing pytest and httpx. The installed
environment's passing pytest run does not exercise this condition.

Required repair: move dependency-requiring tests to integration/boards or
rewrite the core tests to run without dependencies. Keep a real dependency-free
stage; moving dependency installation ahead of it would lose that guarantee.

### P1 — Missing encryption key silently discards encrypted feedback in memory

`src/predoc_pipeline/publish/feedback.py:153` chooses the plaintext path when
the key is absent without checking for an existing `.enc` sibling. A fresh clone
or pipeline run with encrypted feedback but no key therefore loads `{}`. The
pipeline does not have the Telegram-only workflow's missing-key guard. Dashboard
exports can restore previously hidden listings, and local taps can create a
separate plaintext mark history.

Reproduced in an isolated temporary directory: create an encrypted store, save
an `invalid` mark, then reopen without a key. The encrypted file exists, but
`FeedbackStore(path).marks` returns `{}` without an error.

Required repair: fail explicitly when encrypted state exists without a usable
key; exercise pipeline/dashboard/bot callers with that condition. Plaintext-only
local operation remains useful when there is no encrypted state.

## Unfinished requirements in the current changes

- **P2 — Vacancy refresh remains disconnected.** The duplicate-URL branch at
  `src/predoc_pipeline/pipeline.py:491` updates alternate sources and seen hashes,
  then returns. `Database.refresh_listing_facts` has no production caller.
  Changed deadlines/salaries are re-extracted but stored facts remain stale;
  reopened cohorts and refresh-budget rotation are still unresolved. Existing
  helper tests establish field protection, not pipeline refresh behavior.
- **P2 — X thread recovery does not protect scheduled single-post delivery.**
  `src/predoc_pipeline/publish/x.py:378` defaults to `as_thread=False`, calling
  `post_tweet` directly. After a failed web-route X attempt, the pipeline still
  marks the row published (`pipeline.py:748`); `Database.pending_listings`
  selects only pending/unpublished rows. There is no independent X retry
  selector or durable intent for scheduled single posts. The new documentation
  correctly limits journal guarantees to threads; destination recovery remains
  open rather than fixed by the thread tests.

These issues were recorded, not repaired as part of the source expansion.
Type checking also fails in multiple modules (including the new registry and
existing annotation gaps); the advisory CI setting does not make it pass.

## Source expansion delivered

See [source-expansion.md](source-expansion.md), including live discovery/detail
evidence and the disabled NHH boundary. The registry now has **78 boards, 71
enabled and 7 disabled**, plus two disabled feed templates and one disabled
portal template. Configured/enabled counts are not healthy-source counts.

## Verification

- Baseline full suite: 916 passed, 15 subtests passed; one twitter-text
  pkg_resources deprecation warning.
- Final full suite after expansion: 925 passed, 15 subtests passed; the same
  dependency deprecation warning (58.57 seconds).
- Source registry/verification/new adapter contracts: 68 passed.
- Live production HTTP + parsers: Nuffield 1 advert, CREST 3, ESSEC 14; NHH 2
  discovered but a representative Jobbnorge detail yielded only `Laster...`.
- Live production collection for the three enabled additions: 18 discovered,
  17 rejected at the title/role gate, 1 emitted candidate. This candidate has
  not been accepted by extraction or published; it is not a confirmed eligible
  vacancy.
- Final Ruff and whitespace checks pass. Type checking remains failing.
- No model-provider calls, messages, pushes or deployments were performed.

The prior audit's historical repair, complete live coverage, mobile/browser
verification, network boundaries and lifecycle obligations remain open. See
`review/2026-10-05/remaining-work.md`; passing local tests does not close them.
