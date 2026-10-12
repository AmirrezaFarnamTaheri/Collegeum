# Repository review — 12 October 2026

Reviewed branch: `codex/finalize-sources-and-pipeline`, synced base `8b61f84`.
This is a repository review, including orchestration, SQLite/journal recovery,
collectors/adapters, extraction, deduplication, routing, Telegram/X publication,
private feedback, dashboard functions, source configuration, CI and packaging.
The later Telegram improvements are local changes on top of that base.

Integration note: PR #18 subsequently merged main's newer source, subscriber,
private-delivery and packaging implementation. The six findings below describe
the reviewed base `8b61f84`, not an assertion that all remain in current main.
The accompanying reproduction outputs are historical evidence for that base.
See `MERGE_VALIDATION.md` for the integrated branch validation and boundaries.

## Verified remaining defects in the synced base

### P1 — An old cache can erase newer durable publication acknowledgments

`src/predoc_pipeline/core/db.py:977` (`import_rows`) ignores every URL conflict,
regardless of which copy is newer. `state.restore_if_needed` therefore cannot
reconcile a local SQLite cache left behind before a remotely committed send.
The reproduction starts with pending cache row #42 and a newer journal containing
message ID 777: restoration leaves it pending, and `write_journal` overwrites the
acknowledged journal with the stale pending copy. A subsequent run can resend it.
The existing recovery test deliberately preserves newer cache fields, but there
is no timestamp/version ordering that distinguishes this opposite case.
Repair requires explicit reconciliation of lifecycle/acknowledgment state and
fact versions, not an unconditional overwrite in either direction.

### P1 — Early board deduplication drops different vacancies

`src/predoc_pipeline/boards/collector.py:254` suppresses posts from different
sources when their title/employer fingerprint matches, before enrichment.
The fingerprint omits deadline, supervisor and application identity. Two
same-titled roles at the same institution with different URLs, supervisors and
deadlines seven months apart become one emitted item. Later dedupe safeguards
cannot recover the item already discarded. Defer this ambiguous comparison to
the enriched dedupe stage or use stronger shared application identity.

### P1 — Pending recovery bypasses today's publication policy

`src/predoc_pipeline/pipeline.py:1323` appends pending/unpublished rows directly
to the broadcast batch. Only closure checks and hidden marks are reapplied.
The reproduction bans the pending row's employer: `Policy.check_stored` returns
`excluded-employer`, but the full pipeline sends it and marks it published. The
newly accepted/sent set then skips the later preference recheck. Reapply policy
before recovery delivery. The manual `broadcast-pending` command has the same
missing preference/availability gate.

### P2 — Discovery closure evidence does not close the stored listing

`src/predoc_pipeline/pipeline.py:344` records a board's `filled-or-closed`
rejection only in `seen_items`. A previously published listing remains published
and visible until its separately scheduled, bounded recheck reaches it. The
reproduction confirms published status survives explicit collected closure
evidence. Match the existing application identity and apply the appropriate
closure/404-confirmation transition immediately.

### P2 — Preference relaxation does not reconsider unchanged rejected items

The candidate digest in `_pre_extract` contains candidate evidence but excludes
the relevant policy/configuration revision. A stored preference rejection is
reused even after that preference is relaxed. The reproduction allows US jobs
after a prior region rejection but unchanged evidence remains skipped. Version
policy-dependent verdicts or selectively invalidate them when policy changes.

### P2 — Partial link-scan pagination failure looks healthy

`src/predoc_pipeline/boards/scrapers/link_scan.py:161` records later-page fetch
errors only in a local list. If an earlier page succeeded, it returns partial
content without updating adapter diagnostic counters. The reproduction makes
page two fail; source statistics still report `ok=true`, `errors=0`. Add partial
fetch and pagination-cap evidence to the same counters used by Workday and other
adapters, preserving the valid first page.

## Rechecked fixes and changes

Remote sync fixed the earlier unconditional retry of uncertain Telegram sends:
one mocked acknowledgment timeout now produces one attempt and a reconciliation
hold. It also fixed unchanged HTTP feed replay: both identical polls emit the
candidate, allowing unfinished extraction to retry.

The local Telegram enhancement fixes the fresh-runner export retry defect:
the no-new-updates branch can now initialize/restore the database before public
export regeneration. Its regression test preserves the five-record journal.
Cloudflare architecture review additionally prompted transactional quota
reservation, independent chat queues and stale-snapshot rejection.

Distribution verification after sync exposed a stale embedded CI workflow and
cross-platform text normalization omissions for licenses/emoji data, plus the
expected differences from newly added local review files. The local build-tool
change normalizes those text files; regenerate the distribution after all local
source/documentation changes. Do not treat review-induced freshness failure as
proof that every differing file was already stale remotely.

## Evidence and coverage boundaries

- Synced base: **930 tests and 15 subtests passed**; Ruff and strict mypy passed.
- Enhanced implementation: **955 tests and 15 subtests passed**; Ruff and
  strict mypy (66 source files) passed. Worker checks passed **14 tests**,
  including local workerd with real SQLite Durable Object storage and mocked
  network services. Wrangler's deployment dry run passed (34.61 KiB bundle).
  These checks do not establish production delivery or live provider behavior.
- Installed locked Python environment: `pip-audit` reported no known advisories.
  The local project itself is not a PyPI package and was excluded from advisory
  matching; this is not a guarantee against unknown vulnerabilities.
- Source discovery: **48/81 enabled sources passed**, **33 need attention** in
  the bounded `sources verify --timeout 30` run. This includes seasonal empty
  sources accepted by policy; it is not 48 confirmed eligible vacancies.
- Failed/partial discovery and unexpected emptiness are preserved in
  `source-verification-synced.txt`. Timeouts under a 30-second source budget
  require production-budget reproduction before declaring the adapter broken.
  UBC, McGill and Chicago BFI reported partial results; SOMMA, AcademicTransfer,
  UZH, ZEW, RWI, NIESR, BIS and NY Fed need empty-result investigation.
- Earlier pre-sync source failures occurred during DNS/network failure and must
  not be interpreted as simultaneous breakage of every source.
- `reproduce.py` and JSON output record the isolated offline defect proofs.
  Tests and mock acceptance do not establish live Telegram/X/OpenRouter sends.
- Dashboard tests execute selection, history, deadline, CSV and storage logic;
  native browser inspection was blocked by browser/CDP timeouts. Responsive
  visuals/accessibility therefore remain unverified in this review.
- No production deployment, live Telegram writes, credential changes, pushes or
  merges were performed. Cloudflare activation remains a separate external step.

## New Telegram feature review

See [protocol](../../docs/TELEGRAM_PROTOCOL.md) and
[Cloudflare activation](../../cloudflare/telegram/README.md). New database chat
is Telegram-only. The AI produces a validated query or refusal; answers are
rendered from stored records. Public users receive three requests per rolling
minute plus a shared configurable rolling-hour cap. Owners are exempt from
public caps, and public queries cannot read owners' personal marks.

Live acceptance still requires runtime OpenRouter keys, intended Cloudflare
account/owner configuration, deployment approval, initial snapshot sync and
verified Telegram webhook activation. Keys were not loaded in the local
environment; CI wiring reuses the existing OpenRouter secret.
