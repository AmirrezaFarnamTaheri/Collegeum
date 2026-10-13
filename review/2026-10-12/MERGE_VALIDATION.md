# PR #18 integration validation

Integrated the subscriber-capable main branch and subsequently merged its
latest journal/source-health update at `056d2d0` into PR #18, retaining the
reconciled newer publications and curated per-listing corrections. Existing
subscriber navigation, private intent checkpoints, unsubscribe controls,
source expansion, publication state, and release workflows remain preserved.
The generated compile_project.py remains ignored, matching main's policy.

Current source validation (13 October 2026): [CI run 38403211375](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/38403211375)
for commit `0070d913064efa8781d4954959115c12868d2d80` passed all three jobs.
Python 3.11 and 3.12 each passed 1,226 tests plus 21 subtests; Ruff, strict
mypy (75 source files), release verification and stdlib-only core checks
passed. Overall statement coverage was 85%. Worker CI passed 35 tests,
including local workerd/SQLite Durable Object integration; npm audit found
zero reported vulnerabilities. The strict committed-publications gate
passed. The generated single-file build workflow also passed.
The original integrated baseline counted 1,187 Python tests and 18 Worker
tests before these regression cases were added.
The npm dependency audit reported no vulnerabilities. A fresh Python advisory
audit timed out against PyPI; it is not reported as passing. Production behavior
remains outside these offline checks.

Polling retains current subscriber/admin handling and adds /ask and /forget.
Owner browsing adds /menu, /search, /new and /closing. AI quotas and private
query state remain separate from subscriber preferences. Webhook activation
refuses existing subscriber records because the optional Worker does not yet
implement the subscriber protocol. No production webhook was switched.

The Windows runtime now declares tzdata for timezone-aware private delivery.
Tests use an isolated seen-items journal instead of the production journal.

The original REVIEW.md and reproduction files describe base 8b61f84. They must
not be interpreted as six confirmed open defects on this integrated revision.
Live Telegram/OpenRouter delivery and production Worker activation remain
unverified. A Cloudflare token was verified active and stored as a GitHub Actions
secret; its value is absent from repository files and reports.
Three separately stored Cloudflare tokens are now selected in rotation by the
manual workflow. Preflight checks activity and Worker account access, then keeps
one token for deployment and secret upload. All tokens still require Workers
Scripts Edit; no token is created, renewed or revoked by this mechanism.

## 13 October PR remediation and boundaries

- Shared Worker request parsing now prevents quota admission bypass on plain
  `ask`, and public AI requires an explicit `PUBLIC_AI_ENABLED=true` flag.
  Missing flags and the default Wrangler configuration keep public AI disabled.
- Durable Object update checkpoints and alarms recover stalled webhooks;
  valid AI requests are acknowledged only after their inbox and quota admission
  have been committed, then processed asynchronously.
- In-flight duplicates are not acknowledged as delivered. Retries preserve
  provider result, quota admission and feedback mutation checkpoints where
  available. Unknown remote delivery remains **at least once**; duplicate
  Telegram messages remain possible after ambiguous network outcomes.
- Python polling persists quota admissions by update identity so process
  termination before a provider response cannot charge a second slot.
  Full getUpdates tests now exercise owner access, public boundaries, replay
  and an interrupted provider call.
- Bounded single-message database results retain the factual snapshot,
  matching count and shown count. Equal-second Worker snapshot replacements
  invalidate the browsing cache.
- Manual deployment checks runtime secrets before publishing code via
  Wrangler's `deploy --secrets-file`. The deploy workflow remains
  manual and limited to the reviewed default branch; no webhook is registered.

Code quality and offline tests establish these behaviors within controlled
fixtures; they do not establish live Telegram delivery guarantees, actual
OpenRouter availability, deployed Durable Object migration compatibility or
Cloudflare write privileges. Subscriber polling has **not** been migrated to
the optional webhook implementation. No production webhook or deployment
was activated during remediation.

## Pipeline recovery, collection and main-branch reconciliation

The six historical findings in `REVIEW.md` were reproduced with new focused
tests against the prior PR revision (eight failures across core cases), then
addressed in this branch. The historical reproduction JSON and
`review/2026-10-12/reproduce.py` retain their original baseline expectations:
they are archive artifacts, not current-release test verdicts.

- In-run collector deduplication no longer drops two different application
  URLs solely because title and institution match. Identity/fuzzy checks after
  enrichment still decide actual duplicate vacancies.
- A previously pending/unpublished position is rechecked under today's
  publication policy before **both** scheduled and manual broadcasting.
  Preference exclusions remain reversible, rather than being mislabeled
  closed. Manual retry also uses the same link-verification safeguards.
- SQLite cache restoration reconciles publication receipts from the
  committed journal and locally derived database in both directions.
  Different nonempty receipts fail closed for manual investigation; neither
  stale copy silently clears an accepted send. Previously rejected,
  manually reviewed false positives cannot reappear through a stale
  publication snapshot. A strictly newer journal observation updates factual
  fields, while equal-timestamp conflicts preserve local corrections.
- Explicit vacancy-closed evidence from a matching board URL now closes the
  existing stored listing promptly. A first HTTP 404 still requires a second
  independent observation before closure. While that is pending, automatic
  delivery must reverify the original URL (even when general detail
  enrichment is disabled), withhold delivery until verified, and clear the
  hold only after confirmed availability.
- Old `candidate-v3` policy rejection entries are reconsidered under current
  policy once on migration, not only PhD-related rejections.
- Multi-page link scans surface partial fetch failures and a populated
  pagination cap in source-health errors, instead of incorrectly appearing
  fully successful.

The [merge commit c3969ca](https://github.com/AmirrezaFarnamTaheri/Collegeum/commit/c3969cab02d55607dbea908116b4f4e391744105)
integrated the newer `main` data: six additional journal listings and
14 seen-item rows were retained. It preserved a curated rejection for the
Brown University prospect-development role (#185), the corrected
Royal Holloway application URL (#179), and Health Economics disciplines
(#186); dashboard and RSS data were reconciled consistently. The final
source-ci tests confirm the resulting publication integrity.

The project still needs actual production Telegram/OpenRouter delivery tests
and, before activating the optional Worker, a complete subscriber migration.
Network-level Telegram sends cannot offer exactly-once semantics on
uncertain acknowledgements. No deployment, bot-webhook switch or pull-request
merge was performed by this remediation.
