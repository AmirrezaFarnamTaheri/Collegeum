# Collegeum Telegram webhook worker

The current subscriber bot must remain in polling mode. This Worker does not
implement subscriber preferences, alerts or unsubscribe handling. Snapshot sync
refuses activation when private subscriber records exist; do not switch the
production bot's webhook until those flows have been migrated and validated.

Optional instant Telegram browsing and database chat, backed by a SQLite Durable
Object. The existing GitHub pipeline still discovers vacancies and owns the
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
`OPENROUTER_MODEL` defaults to `openrouter/free`.

Worker secrets:

- `TELEGRAM_BOT_TOKEN`: the existing bot token.
- `OPENROUTER_API_KEY`: reuse the existing OpenRouter token. Optional
  `OPENROUTER_API_KEYS` supports additional comma-separated tokens.
- `WEBHOOK_SECRET`: a random Telegram-compatible secret (letters, digits,
  underscores/hyphens; 1–256 characters) used in the webhook header.
- `SYNC_TOKEN`: a separate random secret used only by the pipeline.

Wrangler deployment additionally needs Cloudflare account authentication or a
scoped `CLOUDFLARE_API_TOKEN` with Workers/appropriate storage permissions.
It is never used by the runtime bot and must not be copied into user messages.
Verify the target account with `wrangler whoami` before deployment.
The manual `deploy-telegram-worker` workflow reuses the repository's existing
`OPENROUTER_API_KEY` and `TELEGRAM_BOT_TOKEN`. Supply Cloudflare authentication,
`TELEGRAM_WEBHOOK_SECRET`, and `TELEGRAM_WORKER_SYNC_TOKEN` as GitHub Actions
secrets; set account ID and owner IDs as workflow variables. It is restricted to
reviewed `main` code and never registers the Telegram webhook automatically.

## Activation order

Prepare locally first; deployment, secrets and webhook changes modify external
resources and need the user's explicit approval.

1. Configure the intended owners; deploy the worker to the intended account.
2. Set its runtime secrets securely with Wrangler secret commands.
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
an explicit retention policy rather than silent truncation. Replies with unknown
remote acceptance are held instead of automatically replayed; the user can issue
a new command after checking the chat.

References: [Telegram webhooks](https://core.telegram.org/bots/api#setwebhook),
[Cloudflare Durable Object storage](https://developers.cloudflare.com/durable-objects/best-practices/access-durable-objects-storage/),
[SQLite migrations](https://developers.cloudflare.com/durable-objects/reference/durable-object-class-migrations/),
[OpenRouter tool calling](https://openrouter.ai/docs/features/tool-calling).
