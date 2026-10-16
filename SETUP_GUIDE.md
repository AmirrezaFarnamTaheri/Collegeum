# Collegeum setup and operations (October 2026)

This is the setup guide for the **existing Collegeum GitHub repository**. The
tracked workflows under `.github/workflows/` are authoritative: do not upload
older project ZIPs or manually recreate workflow files from chat messages.
Unreviewed branches must not execute publication jobs.

## 1. Configure GitHub Actions

Keep the repository-wide `GITHUB_TOKEN` default **read-only** in
**Settings → Actions → General**. Workflows needing repository writes must
explicitly declare `contents: write` in their workflow files.
In **Settings → Secrets and variables → Actions**, configure the settings below.

**Public announcements:** set the repository secrets `TELEGRAM_BOT_TOKEN`
and `TELEGRAM_PUBLIC_CHANNEL_ID`. The bot must be an administrator of its
destination channel. The channel ID and the *positive private user ID* of the
admin are different things. Set `TELEGRAM_ADMIN_CHAT_ID` for private owner
commands, if used.

**Private commands/feedback:** set the existing
`FEEDBACK_ENCRYPTION_KEY` secret. This key decrypts saved subscriber state.
Never replace an active key with a new one without a verified re-encryption
migration: doing so can make saved marks/subscriptions unreadable.
Set the repository variable `ENABLE_TELEGRAM_SYNC=true` only after verifying
the key, bot and intended inbox. If private sync is not wanted, keep it
disabled. Public announcements are configured separately.

If credentials are stored as **GitHub Environment secrets**, set the repository
variable `COLLEGEUM_SECRET_ENVIRONMENT` to the correct environment name.
Check that the workflow actually receives the configured environment secrets.

**Recommended subscriber privacy boundary:** create an independently private
GitHub repository for encrypted `data/feedback.enc` and
`data/telegram_state.json`. Copy the **existing** encrypted state there in a
trusted checkout before setting `PRIVATE_STATE_REPO=OWNER/REPOSITORY` and
`PRIVATE_STATE_TOKEN`. The workflows verify that the target is private.
Never start an empty private state over existing subscribers. Follow
[Telegram operations](docs/TELEGRAM_OPERATIONS.md#optional-private-repository-for-subscriber-state)
for the state migration, checkpoint validation and historic privacy caveats.
`PRIVATE_STATE_REPO` is not enabled by merely creating this variable.

The optional `COLLEGEUM_SITE_URL` variable overrides the verified Pages
default `https://amirrezafarnamtaheri.github.io/Collegeum/`. Do not reuse
legacy `SITE_URL` pointing at a different project.

## 2. Extraction and optional integrations

Without any model-provider API key the pipeline uses its deterministic
heuristic extractor. Optional secrets include `GROQ_API_KEY`,
`NVIDIA_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`OPENROUTER_API_KEY`, `MISTRAL_API_KEY`, `GEMINI_API_KEY` and
`CUSTOM_LLM_API_KEY`; set `EXTRACTION_BACKEND` if the automatic
provider selection is not desired. See `.env.example` for the complete
provider options. Do not put keys in TOML or tracked files.

X ingestion is separately gated by `ENABLE_TWITTER=true` and can use the
official `X_BEARER_TOKEN` or `XQUIK_API_KEY`. If both are configured,
quota exhaustion on the official endpoint can fall back to Xquik while
retaining the official provider's errors. Genuine permission-denied
responses do not permit fallback to another unauthorised method.
X broadcasting needs OAuth secrets and is controlled by
`X_BROADCAST_ENABLED`. Check `COMPLIANCE.md` before activating any
scraping or third-party service.

## 3. Run and validate

Under **Actions → predoc-pipeline → Run workflow**, first select
`dry_run=true` to inspect extraction and source health without publishing.
Read its job log and `docs/data/health.json` before a live run.
A *green Actions check* establishes that the workflow completed; it does
**not** guarantee every independent source is healthy. Use the per-source
statuses and recent-run trends in the health dashboard.

The scheduled `predoc-pipeline` workflow runs at **00:07, 04:07, 08:07,
12:07, 16:07, and 20:07 UTC** (four-hour source cohorts). GitHub scheduling,
runner queues and network outages can delay execution.

The `telegram-sync` workflow checks private commands at **:15 and :45
every hour, UTC**, throughout the day—but only if
`ENABLE_TELEGRAM_SYNC=true` and required encryption/bot secrets are
present. GitHub Actions is not an always-on service; a scheduled check may
be delayed. Telegram can discard unconsumed updates after 24 hours, so do
not promise immediate or infallible command delivery.

The optional Cloudflare Telegram Worker is deployed separately through
**Actions → deploy-telegram-worker** on `main`, after configuring its
Cloudflare account, tokens, secret and Owner IDs. Deploying Worker code
does **not** automatically switch Telegram's webhook. Follow
[Telegram operations](docs/TELEGRAM_OPERATIONS.md) to review ownership,
webhook activation, unknown-send reconciliation and rollback.

Never send logs, full exception messages or source failures to vacancy
subscribers. Inspect CI/health privately. Subscriber-facing messages should
contain only supported vacancy/status information.

## 4. Manage sources and records safely

Source definitions live in `config/sources.toml`; filters and routing are in
`config/preferences.toml`. After changing either, run CI and verify representative
live discovery. A source returning 403/418, refusing `robots.txt`, or
requiring human login is **not** an invitation to spoof browser headers or
circumvent access restrictions. Distinguish genuinely empty recruitment
from fetch failures and missing selectors. Temporary upstream failure is
not proof a vacancy closed.

Before manually repairing historical **audit-only false closures**:

1. Pause jobs that write the listing journal; save a trusted checkout of the
   latest `main` with all relevant state and receipts.
2. Preview using `PYTHONPATH=src python3 tools/repair_false_audit_closures.py`.
   Confirm the candidate IDs and exclusion rationale.
3. Run `PYTHONPATH=src python3 tools/repair_false_audit_closures.py --apply`
   only after review. It creates a byte-exact local backup under `build/`,
   clears only specific obsolete audit-generated closure markers, and leaves
   prior Telegram/X receipts intact.
4. Review the journal diff and perform a controlled state checkpoint. Broken
   application links remain suppressed by normal public export quality
   filters. **Do not manually rebroadcast** repaired rows or mistake an
   audit marker for evidence of a genuinely reopened vacancy.

These actions do not erase records from historical public Git commits.

## 5. Troubleshooting

If CI is red, open the failed workflow and inspect the exact failing step.
If source health is degraded but CI is green, inspect `docs/data/health.json`,
identify the failed source and test its official site/permissions separately.
For stale or unanswered private commands, check `ENABLE_TELEGRAM_SYNC`,
bot credentials, encrypted-state restoration and durable send-intent recovery
before retrying. Do **not** blindly replay an ambiguous Telegram send.

GitHub Actions quotas, schedule delays and optional service pricing vary by
account and time. Consult GitHub's current usage/billing page instead of
relying on a fixed historical minutes estimate.
