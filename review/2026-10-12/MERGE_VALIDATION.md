# PR #18 integration validation

Integrated current main (42cc94d) into the Telegram database assistant branch.
Current subscriber navigation, private intent checkpoints, unsubscribe controls,
source expansion, publication state, and release artifact workflows are preserved.
The generated compile_project.py remains ignored, matching main's policy.

Current source validation (13 October 2026): [CI run 38390677429](https://github.com/AmirrezaFarnamTaheri/Collegeum/actions/runs/38390677429)
for commit `d90e655880b9f270a9386460abd59c9fa778e7bf` passed all three jobs.
Python 3.11 and 3.12 each passed 1,209 tests plus 21 subtests, Ruff, strict
mypy (75 source files), release verification and stdlib-only core checks.
Overall statement coverage remained 85%. The Worker passed all 35 tests,
including a real local workerd/SQLite Durable Object test, with no npm audit
vulnerabilities. The strict committed-publications gate passed.
The earlier integration validation counted 1,187 Python tests and 18 Worker
tests before later feature/replay regressions were added.
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

The historical repository-review findings in `REVIEW.md` refer to a
separately reviewed base, and fixes to legacy collector deduplication,
publication-policy recovery and journal conflict resolution are not asserted
by PR #18's scoped CI checks. Revalidate and address those as independent
pipeline work rather than assuming that green Telegram tests close them.
