# PR #18 integration validation

Integrated current main (42cc94d) into the Telegram database assistant branch.
Current subscriber navigation, private intent checkpoints, unsubscribe controls,
source expansion, publication state, and release artifact workflows are preserved.
The generated compile_project.py remains ignored, matching main's policy.

Validation: 1,187 Python tests and 21 subtests passed after integration. The
final refinements passed 80 targeted subscriber, pipeline sync-control and
cloud synchronization tests. Ruff and strict mypy passed (75 source files).
All 18 Worker/rotation tests passed, including local workerd with SQLite storage and
mocked network calls. The strict publication audit reported zero integrity
errors and five existing historical warnings.
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
