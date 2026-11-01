# Collegeum Telegram webhook worker

The Worker answers owner browsing and private subscriber controls immediately.
Subscribers can choose roles and markets, change delivery preferences, switch
English/Persian, pause and unsubscribe. GitHub still collects vacancies and sends
checkpointed alerts on its schedule. Fast menus do not make collection continuous.

My matches uses the same selected roles and career markets as subscriptions.
The user can choose a rolling 7-, 14-, 30-, 60- or 90-day history window
(7 days, 14 days, 1 month, 2 months or 3 months). The default stays 14 days.
The selected window is carried across Next/Previous buttons in the current
browse message; opening My matches again defaults to 14 days. These choices
change browsing only: they do not backfill alerts, resend notifications or
modify delivery receipts. Results depend on records in the latest uploaded
snapshot, not exhaustive LinkedIn search coverage or past vacancy availability.
Owner academic browsing, search and closing-soon views also respect selected
roles. Saved, applied and hidden views
retain explicitly tracked positions even if the subscription changes.
Settings offers 3, 4, 6 or 8 positions per page (default 4). This display preference
is private to the Worker's chat and is removed on unsubscribe; it does not change
the daily alert limit in Alert delivery.

Home groups My matches, Subscriptions, Alert delivery, Settings and Help.
Subscriptions contains Academic roles, Career roles, Life Sciences and Job
markets. Role and market buttons use ☑ for selected and ☐ for not selected.
Alert delivery contains pause/resume and notification controls; Settings leads
to display choices and account controls. Back returns to the parent section.
Owners have a separate Saved & applications section for tracking actions.

The first authenticated protocol-v1 sync seeds existing preferences. Afterward,
Cloudflare owns preference edits; the encrypted Python journal keeps delivery
receipts. Sync imports preferences without replacing receipts. Unsubscribe
tombstones prevent stale snapshots from reactivating a removed subscription.
Older Workers are rejected before local private state changes.

Optional instant Telegram browsing and database chat, backed by a SQLite Durable
Object. Valid AI questions are durably queued and acknowledged before the
OpenRouter request; an alarm processes and delivers the answer after receipt.
Owner browsing commands and callbacks are answered directly. The existing GitHub pipeline still discovers vacancies and owns the
committed listing journal; the worker stores its uploaded snapshot and private
feedback. [Protocol and access rules](../../docs/TELEGRAM_PROTOCOL.md).

## Local verification

The manual deployment workflow rotates its starting credential across the
GitHub secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_API_TOKEN_2` and
`CLOUDFLARE_API_TOKEN_3`. Missing backup secrets are optional. It verifies an
active token with Worker access to the configured account and falls back before
deployment starts; it never retries a
deployment using another credential. This selects existing tokens, and does
not create, renew or revoke them or bypass Cloudflare account quotas.
All tokens require Workers Scripts Edit permission on that same intended account;
the read-only preflight confirms account access, not write authority.

```powershell
cd cloudflare/telegram
npm ci
npm test
npm run check
npm run dev
```

`check` performs a dry-run bundle, not a deployment. `.dev.vars`, `.wrangler`
and `node_modules` are gitignored. Never put real tokens in `wrangler.jsonc`.
`npm test` also runs the bundle in local `workerd` with SQLite Durable Object
storage. All Telegram/OpenRouter egress in that test is intercepted by the local
test service; it never sends a real chat message or spends a real API token.

## Runtime secrets and configuration

Set `OWNER_IDS` to comma-separated positive private Telegram chat IDs.
Keep `PUBLIC_HOURLY_CAP=100` unless changing the shared rolling-hour cap.
Public users always receive three requests per rolling minute; owners are exempt.
`OPENROUTER_MODEL` defaults to `openrouter/free`. Set the deployment variable
`TELEGRAM_AI_ENABLED=false` to disable all AI requests, or
`TELEGRAM_AI_PUBLIC_ENABLED=false` to keep AI owner-only. The manual deployment
workflow defaults public AI to **disabled** until it is explicitly enabled.
These map to the Worker's `AI_ENABLED` and `PUBLIC_AI_ENABLED` bindings.

Worker secrets:

- `TELEGRAM_BOT_TOKEN`: the existing bot token.
- `OPENROUTER_API_KEY`: reuse the existing OpenRouter token. Optional
  `OPENROUTER_API_KEYS` accepts comma, semicolon or whitespace separated tokens,
  or a JSON array of strings. Either setting can be used alone. Plural keys are
  tried first and duplicates are removed, matching the Python pipeline.
- `WEBHOOK_SECRET`: a random Telegram-compatible secret (letters, digits,
  underscores/hyphens; 1–256 characters) used in the webhook header.
- `SYNC_TOKEN`: a separate random secret used only by the pipeline.

Wrangler deployment additionally needs Cloudflare account authentication or a
scoped `CLOUDFLARE_API_TOKEN` with Workers/appropriate storage permissions.
It is never used by the runtime bot and must not be copied into user messages.
Verify the target account with `wrangler whoami` before deployment.
The manual `deploy-telegram-worker` workflow reuses the repository's existing
`OPENROUTER_API_KEY`, optional `OPENROUTER_API_KEYS`, and `TELEGRAM_BOT_TOKEN`.
Supply at least one OpenRouter key through either key setting, Cloudflare authentication,
`TELEGRAM_WEBHOOK_SECRET`, and `TELEGRAM_WORKER_SYNC_TOKEN` as GitHub Actions
secrets; set account ID and owner IDs as workflow variables. It is restricted to
reviewed `main` code and never registers the Telegram webhook automatically.
Each deployment replaces the Worker's OpenRouter keys with the keys currently
configured in GitHub, so switching between the two settings cannot retain old keys.

## Activation order

Prepare locally first; deployment, secrets and webhook changes modify external
resources and need the user's explicit approval.

1. Configure the intended owners; deploy the worker to the intended account.
2. Provide the required runtime secrets to deployment with Wrangler's
   `deploy --secrets-file`, so the code and secrets are uploaded together.
   Do not separately deploy unconfigured code.
3. Set pipeline/Telegram workflow variable `TELEGRAM_WORKER_URL` to the HTTPS
   worker origin and secret `TELEGRAM_WORKER_SYNC_TOKEN` to the matching sync
   token. Preserve the existing feedback encryption key and OpenRouter secret.
4. Enable `TELEGRAM_WEBHOOK_ENABLED=true` and run `telegram-sync` once to seed
   the snapshot and existing feedback. Confirm it completes before switching
   Telegram delivery. This mode sends `/sync`, never `getUpdates`.
5. Register `/webhook` using Telegram `setWebhook`, with the matching
   `secret_token`, `allowed_updates=["message","callback_query"]`, and
   `max_connections=40`. Preserve pending updates (`drop_pending_updates=false`).
6. Confirm `getWebhookInfo` reports the intended URL and no delivery error.
   Test an owner question, public refusal, public rate limit, mark/undo and the
   next scheduled feedback synchronization with the real bot.

`deploy-telegram-worker` defaults to **inspect only**. This read-only mode checks
accounts accessible to existing credentials and reports Telegram's current
delivery mode. Set `inspect_only=false` to deploy reviewed main code. Set
`activate_webhook=true` only after the Worker URL, sync token and webhook secret
are configured and webhook mode is enabled. Activation seeds the snapshot and
preferences, checks authenticated `/status`, registers the webhook without
dropping pending updates, and verifies Telegram reports the intended URL.
`python -S tools/telegram_connection.py` performs the same read-only diagnosis;
`--activate` explicitly enables the checked webhook.

One bot has one Telegram webhook URL. Independent Durable Objects in separate
accounts are not a replicated database. Cross-account load balancing requires
a shared public hostname, health checks and one authoritative state service;
do not point unrelated accounts at the bot and rotate webhook URLs per request.
The three existing tokens belong to different accounts and only credentials
authorized for the selected account can deploy that account's Worker.

Polling and webhooks must not consume updates simultaneously. For rollback,
remove the webhook without dropping pending updates, run a final authenticated
feedback sync, then disable `TELEGRAM_WEBHOOK_ENABLED` and resume polling.

Scheduled snapshot refresh is owned by the Telegram sync workflow; set
`ENABLE_TELEGRAM_SYNC=true` for that workflow. The scraper pipeline runs with
`--no-private-sync` and does not receive the Worker sync credential.

The unauthenticated `/health` endpoint exposes only a service name. `/webhook`
requires the Telegram secret header, and `/sync` requires its separate bearer
token. Neither endpoint serves a browser chat interface. No secret can be read
through the database query grammar.

The implementation bounds snapshots at 2,000 records and 2 MB. Oversized uploads
fail before replacing the existing inventory. Long-term archive growth needs
an explicit retention policy rather than silent truncation. Webhook delivery uses durable update checkpoints and Durable Object alarms to
resume after an interrupted request, even when Telegram stops retrying the
webhook. An interrupted outbound send has **at-least-once**, not exactly-once,
semantics: after a 90-second recovery lease, a retry may duplicate a message
whose first delivery was accepted but whose acknowledgement was lost. Monitor
recovery logs and verify the chat when reconciling ambiguous deliveries.
Pending updates temporarily store inbound command text in private Durable
Object storage until confirmed delivery; completed updates retain only replay
metadata. This is distinct from AI follow-up context, which keeps only
validated query filters.

References: [Telegram webhooks](https://core.telegram.org/bots/api#setwebhook),
[Cloudflare Durable Object storage](https://developers.cloudflare.com/durable-objects/best-practices/access-durable-objects-storage/),
[SQLite migrations](https://developers.cloudflare.com/durable-objects/reference/durable-object-class-migrations/),
[OpenRouter tool calling](https://openrouter.ai/docs/features/tool-calling).
