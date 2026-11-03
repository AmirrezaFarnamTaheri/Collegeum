# Independent ingestion recovery observer

This is a **separate Cloudflare Worker**, not the Telegram bot and not another
GitHub Actions schedule. Its UTC Cron Trigger runs at minute 37 every two
hours. It can notice missed GitHub four-hour ingestion events even when no
GitHub `workflow_run` event is emitted.

**This is deployable code, not a live deployment.** The committed config
defaults to `RECOVERY_ENABLED=false`, so it cannot dispatch until a maintainer
deliberately activates it.

## Recovery safety

- Read only `main:docs/data/health.json` using GitHub's authenticated
  repository contents API. The freshness threshold is **over eight hours**.
- When stale, read the `main` pipeline workflow runs. If any run is active,
  queued, or newer than the published checkpoint (even a failed run), do not
  dispatch.
- Only a valid stale snapshot with trusted, older, completed pipeline history
  authorizes one `pipeline.yml` dispatch on `main` with `dry_run=false`.
- Malformed health, incomplete run history, future clocks, API failures,
  unexpected statuses and missing credentials fail closed. No automatic retry
  of an ambiguous dispatch response.
- The separate Worker has no public recovery endpoint (`fetch()` returns
  HTTP 404) and `workers_dev=false`. It never touches Telegram, subscriber
  records, vacancy journals, or source endpoints, and logs no tokens or raw
  GitHub API responses.

## Deployment: explicit maintainer action

A **Cloudflare account** is required. Merging this PR alone cannot run the
independent cron or verify recovery in production.

1. Create a fine-grained GitHub credential restricted to **only**
   `AmirrezaFarnamTaheri/Collegeum`. Grant **Contents: read** and
   **Actions: write**, no other repository permissions. Set an expiration,
   plan rotation, and never put the credential in a commit, log, or chat.
2. From a trusted checkout, in `cloudflare/telegram/`, use the existing locked
   Wrangler client. Run this dry-run before any deployment:

       npm ci
       npx wrangler deploy --dry-run --config ../ingestion-watchdog/wrangler.jsonc

3. Deploy in the **disabled** state and configure the Worker secret
   interactively (Wrangler prompts for its value; do not use a shell argument):

       npx wrangler deploy --config ../ingestion-watchdog/wrangler.jsonc
       npx wrangler secret put GITHUB_TOKEN --config ../ingestion-watchdog/wrangler.jsonc

4. After checking the deployment name, Cron Trigger and secret binding,
   explicitly opt in:

       npx wrangler deploy --config ../ingestion-watchdog/wrangler.jsonc --var RECOVERY_ENABLED:true

   The CLI flag overrides the checked-in disabled default. A normal redeploy
   without the flag safely disables recovery. Avoid enabling a fork or granting
   the token access to other repositories.

5. Verify that Cloudflare Workers & Pages lists
   `collegeum-ingestion-observer` with `37 */2 * * *` (UTC). Healthy
   invocations log `fresh; action: none` and cause **no** GitHub dispatch.
   When a genuinely stale checkpoint is observed, verify the new
   `predoc-pipeline` workflow-dispatch run, its successful checkpoint, and
   the absence of duplicate Telegram publication. Attach evidence to #52.

To disable, redeploy without the override or disable the Cron Trigger.
The GitHub token must be rotated separately in Cloudflare Worker secrets.

## Limitations and acceptance

- This is independent of the GitHub schedule but cannot guarantee Cloudflare
  will never delay a cron execution. A separate external alerting provider is
  advisable for a strict freshness SLA.
- The GitHub-based watchdog and the external observer have a small
  read-then-dispatch race. Neither makes a global exactly-once promise;
  existing `predoc-bot` concurrency and publishing journals serialize and
  deduplicate side effects.
- A dispatched ingestion is not proof of fresh data, source health, or
  verified-open vacancies. Source-quality acceptance is separate.
- No Cloudflare deployment access or secret was available to this GitHub
  implementation. **Keep #52 open until the live invocation and subsequent
  production checkpoint are independently verified.**
- Offline tests: `node --test cloudflare/ingestion-watchdog/worker.test.mjs`.
  The CI worker job also validates the Wrangler dry-run build.

Related: [#52](https://github.com/AmirrezaFarnamTaheri/Collegeum/issues/52),
[#32](https://github.com/AmirrezaFarnamTaheri/Collegeum/issues/32),
[#80](https://github.com/AmirrezaFarnamTaheri/Collegeum/issues/80).
